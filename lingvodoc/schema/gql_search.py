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
from sqlalchemy.orm.util import aliased


def search_mechanism(dictionaries, category, state_gist_id, limited_gist_id, search_strings, publish, accept, adopted,
                     etymology, yield_batch_count, category_fields):
    state_translation_gist_client_id, state_translation_gist_object_id = state_gist_id
    limited_client_id, limited_object_id = limited_gist_id
    dictionaries = dictionaries.filter(dbDictionary.category == category)
    if publish:
        dictionaries = dictionaries.filter(dbDictionary.marked_for_deletion == False).filter(
            or_(and_(dbDictionary.state_translation_gist_object_id == state_translation_gist_object_id,
                     dbDictionary.state_translation_gist_client_id == state_translation_gist_client_id),
                and_(dbDictionary.state_translation_gist_object_id == limited_object_id,
                     dbDictionary.state_translation_gist_client_id == limited_client_id))). \
            join(dbDictionaryPerspective) \
            .filter(or_(
            and_(dbDictionaryPerspective.state_translation_gist_object_id == state_translation_gist_object_id,
                 dbDictionaryPerspective.state_translation_gist_client_id == state_translation_gist_client_id),
            and_(dbDictionaryPerspective.state_translation_gist_object_id == limited_object_id,
                 dbDictionaryPerspective.state_translation_gist_client_id == limited_client_id))). \
            filter(dbDictionaryPerspective.marked_for_deletion == False)
    lexes = DBSession.query(dbLexicalEntry.client_id, dbLexicalEntry.object_id).join(dbLexicalEntry.parent) \
        .join(dbDictionaryPerspective.parent) \
        .filter(tuple_(dbDictionary.client_id, dbDictionary.object_id).in_(dictionaries))

    if adopted is not None or etymology is not None:
        lexes.join(dbLexicalEntry.entity)
        if adopted is False:
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

    aliases = list()
    and_block = list()
    for search_block in search_strings:
        cur_dbEntity = aliased(dbEntity)
        cur_dbPublishingEntity = aliased(dbPublishingEntity)
        aliases.append(cur_dbEntity)
        aliases.append(cur_dbPublishingEntity)
        # add entity alias in aliases
        or_block = list()
        for search_string in search_block:
            inner_and_block = list()
            if 'field_id' in search_string:
                inner_and_block.append(cur_dbEntity.field_client_id == search_string["field_id"][0])
                inner_and_block.append(cur_dbEntity.field_object_id == search_string["field_id"][1])
            else:
                inner_and_block.append(tuple_(cur_dbEntity.field_client_id, cur_dbEntity.field_object_id).in_(category_fields))

            matching_type = search_string.get('matching_type')
            if matching_type == "full_string":
                if category == 1:
                    inner_and_block.append(cur_dbEntity.additional_metadata['bag_of_words'].contains([search_string["search_string"].lower()]))
                else:
                    inner_and_block.append(func.lower(cur_dbEntity.content) == func.lower(search_string["search_string"]))
            elif matching_type == 'substring':
                if category == 1:
                    inner_and_block.append(func.lower(cur_dbEntity.additional_metadata['bag_of_words'].astext).like("".join(['%', search_string["search_string"].lower(), '%'])))
                else:

                    inner_and_block.append(func.lower(cur_dbEntity.content).like("".join(['%', search_string["search_string"].lower(), '%'])))
            elif matching_type == 'regexp':
                if category == 1:
                    inner_and_block.append(func.lower(cur_dbEntity.additional_metadata['bag_of_words'].astext).op('~*')(search_string["search_string"]))
                else:
                    inner_and_block.append(func.lower(cur_dbEntity.content).op('~*')(search_string["search_string"]))
            else:
                raise ResponseError(message='wrong matching_type')

            or_block.append(and_(*inner_and_block))
        if publish is not None:
            and_block.append(cur_dbPublishingEntity.published == publish)
        if accept is not None:
            and_block.append(cur_dbPublishingEntity.accepted == accept)
        and_block.append(cur_dbEntity.marked_for_deletion == False)
        and_block.append(cur_dbEntity.client_id == cur_dbPublishingEntity.client_id)
        and_block.append(cur_dbEntity.object_id == cur_dbPublishingEntity.object_id)
        and_block.append(cur_dbEntity.parent_client_id == dbLexicalEntry.client_id)
        and_block.append(cur_dbEntity.parent_object_id == dbLexicalEntry.object_id)
        and_block.append(or_(*or_block))
    and_block.append(dbLexicalEntry.parent_client_id == dbDictionaryPerspective.client_id)
    and_block.append(dbLexicalEntry.parent_object_id == dbDictionaryPerspective.object_id)
    and_block.append(dbDictionaryPerspective.parent_client_id == dbDictionary.client_id)
    and_block.append(dbDictionaryPerspective.parent_object_id == dbDictionary.object_id)
    and_block = and_(*and_block)
    aliases_len = len(aliases)
    aliases.append(dbLexicalEntry)
    aliases.append(dbDictionaryPerspective)
    aliases.append(dbDictionary)

    search = DBSession.query(*aliases).filter(and_block, tuple_(dbLexicalEntry.client_id, dbLexicalEntry.object_id).in_(
        lexes)).yield_per(yield_batch_count)
    resolved_search = [entity for entity in search]

    def graphene_entity(entity, publishing):
        ent = Entity(id=(entity.client_id, entity.object_id))
        ent.dbObject = entity
        ent.publishingentity = publishing
        return ent

    def graphene_obj(dbobj, cur_cls):
        obj = cur_cls(id=(dbobj.client_id, dbobj.object_id))
        obj.dbObject = dbobj
        return obj
    full_entities_and_publishing = set()
    for i in range(int(aliases_len / 2)):
        counter = i * 2
        entities_and_publishing = {(entity[counter], entity[counter+1]) for entity in resolved_search}
        full_entities_and_publishing |= entities_and_publishing

    res_entities = [graphene_entity(entity[0], entity[1]) for entity in full_entities_and_publishing]
    tmp_lexical_entries = {entity[aliases_len ] for entity in resolved_search}
    res_lexical_entries = [graphene_obj(ent, LexicalEntry) for ent in tmp_lexical_entries]
    tmp_perspectives = {entity[aliases_len + 1] for entity in resolved_search}
    res_perspectives = [graphene_obj(ent, DictionaryPerspective) for ent in tmp_perspectives]
    tmp_dictionaries = {entity[aliases_len + 2] for entity in resolved_search}
    res_dictionaries = [graphene_obj(ent, Dictionary) for ent in tmp_dictionaries]
    return res_entities, res_lexical_entries, res_perspectives, res_dictionaries

class AdvancedSearch(LingvodocObjectType):
    entities = graphene.List(Entity)
    lexical_entries = graphene.List(LexicalEntry)
    perspectives = graphene.List(DictionaryPerspective)
    dictionaries = graphene.List(Dictionary)

    @classmethod
    def constructor(cls, languages, dicts_to_filter, tag_list, category, adopted, etymology, search_strings, publish, accept):
        yield_batch_count = 200
        dictionaries = DBSession.query(dbDictionary.client_id, dbDictionary.object_id).filter_by(
            marked_for_deletion=False)
        if languages:
            dictionaries = dictionaries.join(dbDictionary.parent).filter(
                tuple_(dbDictionary.parent_client_id, dbDictionary.parent_object_id).in_(languages))
        if dicts_to_filter:
            dictionaries = dictionaries.filter(
                tuple_(dbDictionary.client_id, dbDictionary.object_id).in_(dicts_to_filter))
        if tag_list:
            dictionaries = dictionaries.filter(dbDictionary.additional_metadata["tag_list"].contains(tag_list))

        res_entities = list()
        res_lexical_entries = list()
        res_perspectives = list()
        res_dictionaries = list()

        db_published_gist = translation_gist_search('Published')
        state_translation_gist_client_id = db_published_gist.client_id
        state_translation_gist_object_id = db_published_gist.object_id
        db_la_gist = translation_gist_search('Limited access')
        limited_client_id, limited_object_id = db_la_gist.client_id, db_la_gist.object_id

        text_data_type = translation_gist_search('Text')
        text_fields = DBSession.query(dbField.client_id, dbField.object_id).\
            filter(dbField.data_type_translation_gist_client_id == text_data_type.client_id,
                   dbField.data_type_translation_gist_object_id == text_data_type.object_id).all()

        markup_data_type = translation_gist_search('Markup')
        markup_fields = DBSession.query(dbField.client_id, dbField.object_id). \
            filter(dbField.data_type_translation_gist_client_id == markup_data_type.client_id,
                   dbField.data_type_translation_gist_object_id == markup_data_type.object_id).all()

        # normal dictionaries
        if category != 1:
            res_entities, res_lexical_entries, res_perspectives, res_dictionaries = search_mechanism(
                dictionaries=dictionaries,
                category=0,
                state_gist_id = (state_translation_gist_client_id,
                                state_translation_gist_object_id),
                limited_gist_id = (limited_client_id, limited_object_id),
                search_strings=search_strings,
                publish=publish,
                accept=accept,
                adopted=adopted,
                etymology=etymology,
                category_fields=text_fields,
                yield_batch_count=yield_batch_count
            )


        # corpora
        if category != 0:
            tmp_entities, tmp_lexical_entries, tmp_perspectives, tmp_dictionaries = search_mechanism(
                dictionaries=dictionaries,
                category=1,
                state_gist_id=(state_translation_gist_client_id,
                               state_translation_gist_object_id),
                limited_gist_id=(limited_client_id,
                                 limited_object_id),
                search_strings=search_strings,
                publish=publish,
                accept=accept,
                adopted=adopted,
                etymology=etymology,
                category_fields=markup_fields,
                yield_batch_count=yield_batch_count
            )
            res_entities += tmp_entities
            res_lexical_entries += tmp_lexical_entries
            res_perspectives += tmp_perspectives
            res_dictionaries += tmp_dictionaries

        return cls(entities=res_entities, lexical_entries=res_lexical_entries, perspectives=res_perspectives, dictionaries=res_dictionaries)
