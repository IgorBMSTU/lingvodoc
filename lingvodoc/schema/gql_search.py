import graphene
from lingvodoc.schema.gql_holders import (
    LingvodocObjectType,
    CreatedAt,
    IdHolder,
    MarkedForDeletion,
    AdditionalMetadata,
    Name,
    About,
    del_object,
    acl_check_by_id,
    ResponseError,
    LingvodocID
)
from lingvodoc.models import (
    Organization as dbOrganization,
    Client,
    Dictionary as dbDictionary,
    DictionaryPerspective as dbDictionaryPerspective,
    Language as dbLanguage,
    LexicalEntry as dbLexicalEntry,
    Entity as dbEntity,
    PublishingEntity as dbPublishingEntity,
    User as dbUser,
    BaseGroup as dbBaseGroup,
    Group as dbGroup,
    DBSession,
    Field as dbField
)
from lingvodoc.schema.gql_entity import Entity
from lingvodoc.schema.gql_dictionary import Dictionary
from lingvodoc.schema.gql_dictionaryperspective import DictionaryPerspective
from lingvodoc.schema.gql_lexicalentry import LexicalEntry
from lingvodoc.utils.search import translation_gist_search

from sqlalchemy import (
    func,
    and_,
    or_,
    tuple_,
    not_
)


class AdvancedSearch(LingvodocObjectType):
    entities = graphene.List(Entity)
    lexical_entries = graphene.List(LexicalEntry)
    perspectives = graphene.List(DictionaryPerspective)
    dictionaries = graphene.List(Dictionary)

    @classmethod
    def constructor(cls, languages, tag_list, category, adopted, etymology, search_strings, publish=None, accept=True):
        yield_batch_count = 200
        dictionaries = DBSession.query(dbDictionary.client_id, dbDictionary.object_id).filter_by(
            marked_for_deletion=False)
        if languages:
            dictionaries = dictionaries.join(dbDictionary.parent).filter(
                tuple_(dbDictionary.parent_client_id, dbDictionary.parent_object_id).in_(languages))
        if tag_list:
            dictionaries = dictionaries.filter(dbDictionary.additional_metadata["tag_list"].contains(tag_list))
        # if category is not None:
            # dictionaries = dictionaries.filter(dbDictionary.category == category)

        res_entities = list()
        res_lexical_entries = list()
        res_perspectives = list()
        res_dictionaries = list()
        # normal dictionaries
        if category != 1:
            normal_dictionaries = dictionaries.filter(dbDictionary.category == 0)
            lexes = DBSession.query(dbLexicalEntry.client_id, dbLexicalEntry.object_id).join(dbLexicalEntry.parent) \
                .join(dbDictionaryPerspective.parent) \
                .filter(tuple_(dbDictionary.client_id, dbDictionary.object_id).in_(
                normal_dictionaries))

            if adopted is not None or etymology is not None:
                lexes.join(dbLexicalEntry.entity)
                if adopted is False:
                    # lexes = lexes.filter(~dbEntity.content.ilike('заим.%'))
                    lexes = lexes.filter(~func.lower(dbEntity.content).contains('заим.%'))
                elif adopted:
                    lexes = lexes.filter(func.lower(dbEntity.content).contains('заим.%'))
                if etymology is not None:
                    gist = translation_gist_search('Grouping Tag')
                    fields = DBSession.query(dbField.client_id, dbField.object_id).filter(
                        tuple_(dbField.data_type_translation_gist_client_id,
                               dbField.data_type_translation_gist_object_id) == (gist.client_id, gist.object_id))
                    if etymology:
                        lexes = lexes.filter(not_(tuple_(dbEntity.field_client_id, dbEntity.field_object_id).in_(fields)))
                    else:
                        lexes = lexes.filter(tuple_(dbEntity.field_client_id, dbEntity.field_object_id).in_(fields))

            lexes = lexes.yield_per(yield_batch_count)

            basic_search = DBSession.query(dbEntity, dbPublishingEntity, dbLexicalEntry, dbDictionaryPerspective, dbDictionary).join(dbEntity.parent).join(
                dbEntity.publishingentity) \
                .join(dbLexicalEntry.parent).join(dbDictionaryPerspective.parent).filter(
                dbPublishingEntity.client_id == dbEntity.client_id,
                dbPublishingEntity.object_id == dbEntity.object_id
            )

            if publish is not None:
                basic_search = basic_search.filter(dbPublishingEntity.published == publish)
            if accept is not None:
                basic_search = basic_search.filter(dbPublishingEntity.accepted == accept)

            and_block = list()
            for search_block in search_strings:
                or_block = list()
                for search_string in search_block:
                    inner_and_block = list()
                    if 'field_id' in search_string:
                        inner_and_block.append(dbEntity.field_client_id == search_string["field_id"][0])
                        inner_and_block.append(dbEntity.field_object_id == search_string["field_id"][1])
                    else:
                        pass
                    # todo: search by Text fields

                    matching_type = search_string.get('matching_type')
                    if matching_type == "full_string":
                        inner_and_block.append(func.lower(dbEntity.content) == func.lower(search_string["search_string"]))
                    elif matching_type == 'substring':
                        inner_and_block.append(dbEntity.content.like("".join(['%', search_string["search_string"].lower(), '%'])))
                    elif matching_type == 'regexp':
                        inner_and_block.append(dbEntity.content.op('~*')(search_string["search_string"]))
                    else:
                        raise ResponseError(message='wrong matching_type')
                    or_block.append(and_(*inner_and_block))

                and_block.append(or_(*or_block))
            and_block = and_(*and_block)

            # lexes_composite_list = [(lex.client_id, lex.object_id, lex.parent_client_id, lex.parent_object_id)
            #                 for lex in lexes.yield_per(100)]

            # for lex in lexes:
            #     dbentities = DBSession.query(dbEntity).filter_by(parent=lex).all()
            #     entities = [Entity(id=[ent.client_id, ent.object_id]) for ent in dbentities]
            #     result.append(LexicalEntry(id=[lex.client_id, lex.object_id], entities = entities))
            # search = dbLexicalEntry.graphene_track_multiple(lexes_composite_list,
            #                                            publish=publish, accept=accept, and_clause=and_block)

            search = basic_search.filter(and_block, tuple_(dbLexicalEntry.client_id, dbLexicalEntry.object_id).in_(
                lexes)).yield_per(yield_batch_count)

            def graphene_entity(entity, publishing):
                ent = Entity(id=(entity.client_id, entity.object_id))
                ent.dbObject = entity
                ent.publishingentity = publishing
                return ent

            def graphene_obj(dbobj, cur_cls):
                obj = cur_cls(id=(dbobj.client_id, dbobj.object_id))
                obj.dbObject = dbobj
                return obj

            res_entities = [graphene_entity(entity[0], entity[1]) for entity in search]
            lexical_entries = {entity[2] for entity in search}
            res_lexical_entries = [graphene_obj(ent, LexicalEntry) for ent in lexical_entries]
            perspectives = {entity[3] for entity in search}
            res_perspectives = [graphene_obj(ent, DictionaryPerspective) for ent in perspectives]
            res_dictionaries = {entity[4] for entity in search}
            res_dictionaries = [graphene_obj(ent, Dictionary) for ent in res_dictionaries]
            # return cls(entities=entities, lexical_entries=lexical_entries, perspectives=perspectives, dictionaries=dictionaries)

        # corpora
        if category != 0:
            corporas = dictionaries.filter(dbDictionary.category == 1)

            lexes = DBSession.query(dbLexicalEntry.client_id, dbLexicalEntry.object_id).join(dbLexicalEntry.parent) \
                .join(dbDictionaryPerspective.parent) \
                .filter(tuple_(dbDictionary.client_id, dbDictionary.object_id).in_(
                corporas))

            if adopted is not None or etymology is not None:
                lexes.join(dbLexicalEntry.entity)
                if adopted is False:
                    # lexes = lexes.filter(~dbEntity.content.ilike('заим.%'))
                    lexes = lexes.filter(~func.lower(dbEntity.content).contains('заим.%'))
                elif adopted:
                    lexes = lexes.filter(func.lower(dbEntity.content).contains('заим.%'))
                if etymology is not None:
                    gist = translation_gist_search('Grouping Tag')
                    fields = DBSession.query(dbField.client_id, dbField.object_id).filter(
                        tuple_(dbField.data_type_translation_gist_client_id,
                               dbField.data_type_translation_gist_object_id) == (gist.client_id, gist.object_id))
                    if etymology:
                        lexes = lexes.filter(not_(tuple_(dbEntity.field_client_id, dbEntity.field_object_id).in_(fields)))
                    else:
                        lexes = lexes.filter(tuple_(dbEntity.field_client_id, dbEntity.field_object_id).in_(fields))

            lexes = lexes.yield_per(yield_batch_count)

            basic_search = DBSession.query(dbEntity, dbPublishingEntity, dbLexicalEntry, dbDictionaryPerspective, dbDictionary).join(dbEntity.parent).join(
                dbEntity.publishingentity) \
                .join(dbLexicalEntry.parent).join(dbDictionaryPerspective.parent).filter(
                dbPublishingEntity.client_id == dbEntity.client_id,
                dbPublishingEntity.object_id == dbEntity.object_id
            )

            if publish is not None:
                basic_search = basic_search.filter(dbPublishingEntity.published == publish)
            if accept is not None:
                basic_search = basic_search.filter(dbPublishingEntity.accepted == accept)

            and_block = list()
            for search_block in search_strings:
                or_block = list()
                for search_string in search_block:
                    inner_and_block = list()
                    if 'field_id' in search_string:
                        inner_and_block.append(dbEntity.field_client_id == search_string["field_id"][0])
                        inner_and_block.append(dbEntity.field_object_id == search_string["field_id"][1])
                    else:
                        pass

                    matching_type = search_string.get('matching_type')
                    if matching_type == "full_string":
                        inner_and_block.append(dbEntity.additional_metadata['bag_of_words'].contains([search_string["search_string"].lower()]))
                    elif matching_type == 'substring':
                        inner_and_block.append(func.lower(dbEntity.additional_metadata['bag_of_words'].astext).like("".join(['%', search_string["search_string"].lower(), '%'])))
                    elif matching_type == 'regexp':
                        inner_and_block.append(func.lower(dbEntity.additional_metadata['bag_of_words'].astext).op('~*')(search_string["search_string"]))
                    else:
                        raise ResponseError(message='wrong matching_type')
                    or_block.append(and_(*inner_and_block))

                and_block.append(or_(*or_block))
            and_block = and_(*and_block)

            # lexes_composite_list = [(lex.client_id, lex.object_id, lex.parent_client_id, lex.parent_object_id)
            #                 for lex in lexes.yield_per(100)]

            # for lex in lexes:
            #     dbentities = DBSession.query(dbEntity).filter_by(parent=lex).all()
            #     entities = [Entity(id=[ent.client_id, ent.object_id]) for ent in dbentities]
            #     result.append(LexicalEntry(id=[lex.client_id, lex.object_id], entities = entities))
            # search = dbLexicalEntry.graphene_track_multiple(lexes_composite_list,
            #                                            publish=publish, accept=accept, and_clause=and_block)

            search = basic_search.filter(and_block, tuple_(dbLexicalEntry.client_id, dbLexicalEntry.object_id).in_(
                lexes)).yield_per(yield_batch_count)

            # search = basic_search.filter(and_block)

            def graphene_entity(entity, publishing):
                ent = Entity(id=(entity.client_id, entity.object_id))
                ent.dbObject = entity
                ent.publishingentity = publishing
                return ent

            def graphene_obj(dbobj, cur_cls):
                obj = cur_cls(id=(dbobj.client_id, dbobj.object_id))
                obj.dbObject = dbobj
                return obj

            entities = [graphene_entity(entity[0], entity[1]) for entity in search]
            res_entities += entities
            lexical_entries = {entity[2] for entity in search}
            lexical_entries = [graphene_obj(ent, LexicalEntry) for ent in lexical_entries]
            res_lexical_entries += lexical_entries
            perspectives = {entity[3] for entity in search}
            perspectives = [graphene_obj(ent, DictionaryPerspective) for ent in perspectives]
            res_perspectives += perspectives
            tmp_dictionaries = {entity[4] for entity in search}
            tmp_dictionaries = [graphene_obj(ent, Dictionary) for ent in tmp_dictionaries]
            res_dictionaries += tmp_dictionaries
        return cls(entities=res_entities, lexical_entries=res_lexical_entries, perspectives=res_perspectives, dictionaries=res_dictionaries)

        # todo: what if there corpora and dictionaries