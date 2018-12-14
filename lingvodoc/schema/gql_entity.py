import os
import shutil
from pathvalidate import sanitize_filename
import graphene
from sqlalchemy import and_, tuple_
from lingvodoc.models import DBSession
from lingvodoc.schema.gql_holders import (
    fetch_object,
    ObjectVal,
    Upload)
from lingvodoc.models import (
    Entity as dbEntity,
    Client,
    User as dbUser,
    DBSession,
    LexicalEntry as dbLexicalEntry,
    TranslationAtom as dbTranslationAtom,
    TranslationGist as dbTranslationGist,
    Field as dbField,
    Group as dbGroup,
    BaseGroup as dbBaseGroup,
    PublishingEntity as dbPublishingEntity,
    DictionaryPerspective as dbDictionaryPerspective

)
from lingvodoc.schema.gql_holders import (
    LingvodocObjectType,
    CompositeIdHolder,
    CreatedAt,
    Relationship,
    SelfHolder,
    FieldHolder,
    ParentLink,
    MarkedForDeletion,
    AdditionalMetadata,
    LocaleId,
    Content,
    del_object,
    ResponseError,
    client_id_check,
    Published,
    Accepted,
    LingvodocID

)
from sqlalchemy import (
    and_,
)

# from lingvodoc.views.v2.utils import (
#     create_object
# )

import base64
import hashlib

from lingvodoc.models import DictionaryPerspective as dbPerspective
from lingvodoc.utils.creation import create_entity
from lingvodoc.utils.deletion import real_delete_entity

from lingvodoc.utils.verification import check_lingvodoc_id, check_client_id

from lingvodoc.utils.elan_functions import eaf_wordlist


def object_file_path(obj, base_path, folder_name, filename, create_dir=False):
    filename = sanitize_filename(filename)
    storage_dir = os.path.join(base_path, obj.__tablename__, folder_name, str(obj.client_id), str(obj.object_id))
    if create_dir:
        os.makedirs(storage_dir, exist_ok=True)
    storage_path = os.path.join(storage_dir, filename)
    return storage_path, filename


def create_object(content, obj, data_type, filename, folder_name, storage, json_input=True):
    import errno
    storage_path, filename = object_file_path(obj, storage["path"], folder_name, filename, True)
    directory = os.path.dirname(storage_path)  # TODO: find out, why object_file_path were not creating dir
    try:
        os.makedirs(directory)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise
    with open(str(storage_path), 'wb+') as f:
        if json_input:
            f.write(content)
        else:
            shutil.copyfileobj(content, f)

    real_location = storage_path
    url = "".join((storage["prefix"],
                   storage["static_route"],
                   obj.__tablename__,
                   '/',
                   folder_name,
                   '/',
                   str(obj.client_id), '/',
                   str(obj.object_id), '/',
                   filename))
    return real_location, url


# Read
class Entity(LingvodocObjectType):
    """
        query myQuery {
      entity(id: [66, 298] ){
				id
				created_at
			}

		}
    """
    # TODO: Accepted, entity_type
    content = graphene.String()
    data_type = graphene.String()
    dbType = dbEntity
    publishingentity = None

    class Meta:
        interfaces = (CompositeIdHolder,
                      AdditionalMetadata,
                      CreatedAt,
                      MarkedForDeletion,
                      Relationship,
                      SelfHolder,
                      FieldHolder,
                      ParentLink,
                      Content,
                      # TranslationHolder,
                      LocaleId,
                      Published,
                      Accepted
                      )

    @fetch_object('data_type')
    def resolve_data_type(self, info):
        return self.dbObject.field.data_type


# Create
class CreateEntity(graphene.Mutation):
    class Arguments:
        """
        input values from request. Look at "LD methods" exel table
        """
        id = LingvodocID()
        parent_id = LingvodocID(required=True)
        additional_metadata = ObjectVal()
        field_id = LingvodocID(required=True)
        self_id = LingvodocID()
        link_id = LingvodocID()
        link_perspective_id = LingvodocID()

        locale_id = graphene.Int()
        filename = graphene.String(

        )
        content = graphene.String()
        registry = ObjectVal()
        file_content = Upload()

    # Result object

    entity = graphene.Field(Entity)

    """
    example:
    curl -i -X POST  -H "Cookie: auth_tkt="
    -H "Content-Type: multipart/form-data" -F "blob=@белка.wav" -F 'query=mutation {
            create_entity(parent_id: [66, 69],  field_id:  [66,12] ) {entity{id, parent_id} triumph}}' http://localhost:6543/graphql

    or
    mutation  {
    create_entity(parent_id: [66, 69], field_id: [66, 6], content: "test") {
        entity {
            created_at,
	content
        }

    triumph
    }
    }
    """
    # Used for convenience

    triumph = graphene.Boolean()

    @staticmethod
    @client_id_check()
    def mutate(root, info, **args):
        id = args.get('id')
        client_id = id[0] if id else info.context["client_id"]
        object_id = id[1] if id else None
        lexical_entry_id = args.get('parent_id')
        locale_id = args.get('locale_id')
        if not locale_id:
            locale_id=2
        if not lexical_entry_id:
            raise ResponseError(message="Lexical entry not found")
        parent_client_id, parent_object_id = lexical_entry_id
        client = DBSession.query(Client).filter_by(id=client_id).first()
        user = DBSession.query(dbUser).filter_by(id=client.user_id).first()
        if not user:
            raise ResponseError(message="This client id is orphaned. Try to logout and then login once more.")

        parent = DBSession.query(dbLexicalEntry).filter_by(client_id=parent_client_id, object_id=parent_object_id).first()
        if not parent:
            raise ResponseError(message="No such lexical entry in the system")

        info.context.acl_check('create', 'lexical_entries_and_entities',
            (parent.parent_client_id, parent.parent_object_id))

        additional_metadata = args.get('additional_metadata')
        upper_level = None

        field_client_id, field_object_id = args.get('field_id')
        tr_atom = DBSession.query(dbTranslationAtom).join(dbTranslationGist, and_(
            dbTranslationAtom.locale_id == 2,
            dbTranslationAtom.parent_client_id == dbTranslationGist.client_id,
            dbTranslationAtom.parent_object_id == dbTranslationGist.object_id)).join(dbField, and_(
            dbTranslationGist.client_id == dbField.data_type_translation_gist_client_id,
            dbTranslationGist.object_id == dbField.data_type_translation_gist_object_id)).filter(
            dbField.client_id == field_client_id, dbField.object_id == field_object_id).first()
        if not tr_atom:
             raise ResponseError(message="No such field in the system")
        data_type = tr_atom.content.lower()

        if args.get('self_id'):
            self_client_id, self_object_id = args.get('self_id')
            upper_level = DBSession.query(dbEntity).filter_by(client_id=self_client_id,
                                                            object_id=self_object_id).first()
            if not upper_level:
                raise ResponseError(message="No such upper level in the system")
        dbentity = dbEntity(client_id=client_id,
                        object_id=object_id,
                        field_client_id=field_client_id,
                        field_object_id=field_object_id,
                        locale_id=locale_id,
                        additional_metadata=additional_metadata,
                        parent=parent)

        # Acception override check.
        # Currently disabled.

        #group = DBSession.query(dbGroup).join(dbBaseGroup).filter(dbBaseGroup.subject == 'lexical_entries_and_entities',
        #                                                      dbGroup.subject_client_id == dbentity.parent.parent.client_id,
        #                                                      dbGroup.subject_object_id == dbentity.parent.parent.object_id,
        #                                                      dbBaseGroup.action == 'create').one()

        #override_group = DBSession.query(dbGroup).join(dbBaseGroup).filter(
        #    dbBaseGroup.subject == 'lexical_entries_and_entities',
        #    dbGroup.subject_override == True,
        #    dbBaseGroup.action == 'create').one()

        #if user in group.users or user in override_group.users:
        #    dbentity.publishingentity.accepted = True

        if upper_level:
            dbentity.upper_level = upper_level

        dbentity.publishingentity.accepted = True

        # If the entity is being created by the admin, we automatically publish it.

        if user.id == 1:
          dbentity.publishingentity.published = True

        filename = args.get('filename')
        real_location = None
        url = None
        if data_type == 'image' or data_type == 'sound' or 'markup' in data_type:
            blob = info.context.request.POST.pop("0")
            filename=blob.filename
            content = blob.file.read()
            #filename=
            real_location, url = create_object(content, dbentity, data_type, filename, "graphql_files", info.context.request.registry.settings["storage"])
            dbentity.content = url
            old_meta = dbentity.additional_metadata
            need_hash = True
            if old_meta:
                if old_meta.get('hash'):
                    need_hash = False
            if need_hash:
                hash = hashlib.sha224(content).hexdigest()
                hash_dict = {'hash': hash}
                if old_meta:
                    old_meta.update(hash_dict)
                else:
                    old_meta = hash_dict
                dbentity.additional_metadata = old_meta
            if 'markup' in data_type:
                name = filename.split('.')
                ext = name[len(name) - 1]
                if ext.lower() == 'textgrid':
                    data_type = 'praat markup'

                elif ext.lower() == 'eaf':
                    data_type = 'elan markup'

            dbentity.additional_metadata['data_type'] = data_type

            if 'elan' in data_type:
                bag_of_words = list(eaf_wordlist(dbentity))
                dbentity.additional_metadata['bag_of_words'] = bag_of_words
        elif data_type == 'link':
            if args.get('link_id'):
                link_client_id, link_object_id = args.get('link_id')
                dbentity.link_client_id = link_client_id
                dbentity.link_object_id = link_object_id
            else:
                raise ResponseError(
                    message="The field is of link type. You should provide client_id and object id in the content")
        elif data_type == 'directed link':
            if args.get('link_id'):
                link_client_id, link_object_id = args.get('link_id') # TODO: le check
                dbentity.link_client_id = link_client_id
                dbentity.link_object_id = link_object_id
            else:
                raise ResponseError(
                    message="The field is of link type. You should provide client_id and object id in the content")
            if args.get("link_perspective_id"):
                link_persp_client_id, link_persp_object_id = args.get('link_perspective_id')
                if not DBSession.query(dbPerspective)\
                        .filter_by(client_id=link_persp_client_id, object_id=link_persp_object_id).first():
                    raise ResponseError(message="link_perspective not found")
                dbentity.additional_metadata['link_perspective_id'] = [link_persp_client_id, link_persp_object_id]

            else:
                raise ResponseError(
                    message="The field is of link type. You should provide link_perspective_id id in the content")

        else:
            content = args.get("content")
            dbentity.content = content

            # if args.get('is_translatable', None): # TODO: fix it
            #     field.is_translatable = bool(args['is_translatable'])
        DBSession.add(dbentity)
        DBSession.flush()
        entity = Entity(id = [dbentity.client_id, dbentity.object_id])
        entity.dbObject = dbentity
        return CreateEntity(entity=entity, triumph=True)

        # if not perm_check(client_id, "field"):
        #    return ResponseError(message = "Permission Denied (Entity)")


    # Update
    """
    example #1:
    mutation  {
        update_entity(id: [ 742, 5494], additional_metadata: {hash:"1234567"} ) {
            entity {
                created_at,
                additional_metadata{
                hash
                }
            }

        status
        }
    }
    example #2:
    mutation  {
        update_entity(id: [ 742, 5494], additional_metadata: {hash:"12345"} ){status}
    }
    resolve:
    {
        "update_entity": {
            "status": true
        }
    }
    """
    # Delete
    """
    query:
    mutation  {
        delete_entity(id: [879, 8]) {
        entity{id, content, created_at}
        status
        }
    }
    response:
    {
        "delete_entity": {
            "entity": {
                "id": [
                    879,
                    8
                ],
                "content": "123",
                "created_at": "2017-06-27T09:49:24"
            },
            "status": true
        }
    }
    or
    {
        "errors": [
            "No such entity in the system"
        ]
    }
    """


class UpdateEntity(graphene.Mutation):
    """
    mutation Mu{
	update_entity_content(id:[1995,2017], published: true){
		entity{
			created_at
		}
	}
    }
    """
    class Arguments:
        id = LingvodocID(required=True)
        published = graphene.Boolean()
        accepted = graphene.Boolean()

    entity = graphene.Field(Entity)
    triumph = graphene.Boolean()

    @staticmethod
    def mutate(root, info, **args):
        client_id, object_id = args.get('id')
        dbpublishingentity = DBSession.query(dbPublishingEntity).filter_by(client_id=client_id,
                                                                           object_id=object_id).first()
        if not dbpublishingentity:
            raise ResponseError(message="No such entity in the system")
        # lexical_entry = dbpublishingentity.parent.parent
        lexical_entry = DBSession.query(dbLexicalEntry).join(dbLexicalEntry.entity).join(
            dbEntity.publishingentity).filter(dbPublishingEntity.client_id == client_id,
                                              dbPublishingEntity.object_id == object_id).one()
        if not lexical_entry:
            raise ResponseError(message="No such lexical_entry in the system")
        published = args.get('published')
        accepted = args.get('accepted')
        if published is not None and not dbpublishingentity.published:
            info.context.acl_check('create', 'approve_entities',
                                   (lexical_entry.parent_client_id, lexical_entry.parent_object_id))

        if published is not None and not published and dbpublishingentity.published:
            info.context.acl_check('delete', 'approve_entities',
                                   (lexical_entry.parent_client_id, lexical_entry.parent_object_id))

        if accepted is not None and not dbpublishingentity.accepted:
            info.context.acl_check('create', 'lexical_entries_and_entities',
                                   (lexical_entry.parent_client_id, lexical_entry.parent_object_id))

        if accepted is not None and not accepted and dbpublishingentity.accepted:
            raise ResponseError(message="Not allowed action")

        if published is not None:
            dbpublishingentity.published = published
        if accepted is not None:
            dbpublishingentity.accepted = accepted

        dbentity = DBSession.query(dbEntity).filter_by(client_id=client_id, object_id=object_id).first()
        entity = Entity(id=[dbentity.client_id, dbentity.object_id])
        entity.dbObject = dbentity
        return UpdateEntity(entity=entity, triumph=True)


class ApproveAllForUser(graphene.Mutation):
    """
    mutation Mu{
	update_entity_content(id:[1995,2017], published: true){
		entity{
			created_at
		}
	}
    }
    """
    class Arguments:
        user_id = graphene.Int()
        published = graphene.Boolean()
        accepted = graphene.Boolean()
        field_ids = graphene.List(LingvodocID)
        perspective_id = LingvodocID(required=True)

    #entity = graphene.Field(Entity)
    triumph = graphene.Boolean()

    @staticmethod
    def mutate(root, info, **args):
        user_id = args.get('user_id')
        published = args.get('published')
        accepted = args.get('accepted')
        field_ids = args.get('field_ids')
        perspective_id = args.get('perspective_id')

        given_perspective = DBSession.query(dbDictionaryPerspective).filter_by(marked_for_deletion=False,
                                                                               client_id = perspective_id[0],
                                                                               object_id = perspective_id[1]).first()
        if not given_perspective:
            raise ResponseError("Perspective Not found")
        if published is not None:
            info.context.acl_check('create', 'approve_entities',
                                   (perspective_id[0], perspective_id[1]))

        if published is not None:
            info.context.acl_check('delete', 'approve_entities',
                                   (perspective_id[0], perspective_id[1]))

        if accepted is not None:
            info.context.acl_check('create', 'lexical_entries_and_entities',
                                   (perspective_id[0], perspective_id[1]))

        # query(dbEntity).join(dbEntity.parent).join(dbEntity.publishingentity).filter(
        #     dbPublishingEntity.accepted == false, dbLexicalEntry.parent == given_perspective,
        #     dbEntity.client_id.in_(list_of_clients_of_given_user, dbEntity.field.in_(list_of_fields))).all()



        list_of_clients_of_given_user = [x[0] for x in DBSession.query(Client.id).filter_by(user_id=user_id).all()]
        list_of_fields = list()
        for field_id in field_ids:
            field = DBSession.query(dbField).filter_by(client_id=field_id[0], object_id=field_id[1]).first()
            if not field:
                raise ResponseError("field not found")
            list_of_fields.append((field.client_id, field.object_id))
        field_id_list = tuple(list_of_fields)
        pub_entities = None
        if published:
            pub_entities = DBSession.query(dbPublishingEntity).join(dbEntity.parent).join(dbEntity.publishingentity).filter(
                dbPublishingEntity.published==False,
                dbLexicalEntry.parent==given_perspective,
                tuple_(dbEntity.field_client_id, dbEntity.field_object_id).in_(field_id_list),
                dbEntity.client_id.in_(list_of_clients_of_given_user)
            ).all()
        if accepted:
            pub_entities = DBSession.query(dbPublishingEntity).join(dbEntity.parent).join(dbEntity.publishingentity).filter(
                dbPublishingEntity.accepted==False,
                dbLexicalEntry.parent==given_perspective,
                tuple_(dbEntity.field_client_id, dbEntity.field_object_id).in_(field_id_list),
                dbEntity.client_id.in_(list_of_clients_of_given_user)
            ).all()
        for pub_entity in pub_entities:
            if published:
                pub_entity.published = True
            if accepted:
                pub_entity.accepted = True
        DBSession.flush()
        # if accepted is not None and not accepted and dbpublishingentity.accepted:
        #     raise ResponseError(message="Not allowed action")

        # client_id = id[0] if id else info.context["client_id"]
        # object_id = id[1] if id else None

        return ApproveAllForUser( triumph=True)



class DeleteEntity(graphene.Mutation):
    class Arguments:
        id = LingvodocID(required=True)

    triumph = graphene.Boolean()
    entity = graphene.Field(Entity)

    @staticmethod
    def mutate(root, info, **args):
        client_id, object_id = args.get('id')
        dbentity = DBSession.query(dbEntity).filter_by(client_id=client_id, object_id=object_id).first()
        if not dbentity or dbentity.marked_for_deletion:
            raise ResponseError(message="No such entity in the system")
        lexical_entry = dbentity.parent
        info.context.acl_check('delete', 'lexical_entries_and_entities',
                               (lexical_entry.parent_client_id, lexical_entry.parent_object_id))

        settings = info.context["request"].registry.settings
        if 'desktop' in settings:
            real_delete_entity(dbentity, settings)
        else:
            del_object(dbentity)
        entity = Entity(id=[client_id, object_id])
        entity.dbObject = dbentity
        return DeleteEntity(entity=entity, triumph=True)



class BulkCreateEntity(graphene.Mutation):
    """
    mutation {
            bulk_create_entity(entities: [{id: [1199, 4], parent_id: [66, 69],  field_id:  [66, 6]}]) {
                   triumph
        }
    }
    """

    class Arguments:
        entities = graphene.List(ObjectVal)
    entities = graphene.List(Entity)
    triumph = graphene.Boolean()

    @staticmethod
    def mutate(root, info, **args):
        client = DBSession.query(Client).filter_by(id=info.context["client_id"]).first()
        if not client:
            raise KeyError("Invalid client id (not registered on server). Try to logout and then login.",
                           info.context["client_id"])
        entity_objects = args.get('entities')
        dbentities_list = list()
        request = info.context.request
        entities = list()
        for entity_obj in entity_objects:
            ids = entity_obj.get("id")  # TODO: id check

            if ids is None:
                ids = (info.context["client_id"], None)
            else:
                if not check_lingvodoc_id(ids):
                    raise KeyError("Wrong id")
                if not check_client_id(info.context["client_id"], ids[0]):
                    raise KeyError("Invalid client id (not registered on server). Try to logout and then login.",
                                   ids[0])
            parent_id = entity_obj.get("parent_id")

            if not parent_id:
                raise ResponseError(message="Bad lexical_entry object")
            if not check_lingvodoc_id(parent_id):
                raise KeyError("Wrong parent_id")
            lexical_entry = DBSession.query(dbLexicalEntry) \
                .filter_by(client_id=parent_id[0], object_id=parent_id[1]).one()
            info.context.acl_check('create', 'lexical_entries_and_entities',
                                   (lexical_entry.parent_client_id, lexical_entry.parent_object_id))

            additional_metadata = None
            if 'additional_metadata' in entity_obj:
                additional_metadata = entity_obj["additional_metadata"]
            field_id = entity_obj.get('field_id')
            if not check_lingvodoc_id(field_id):
                raise ResponseError('no field_id provided')
            self_id = entity_obj.get("self_id")
            if self_id:
                if not check_lingvodoc_id(self_id):
                    raise KeyError("Wrong self_id")
            link_id = entity_obj.get("link_id")
            if link_id:
                if not check_lingvodoc_id(link_id):
                    raise KeyError("Wrong link_id")
            locale_id = entity_obj.get("locale_id", 2)
            filename = entity_obj.get("filename")
            content = entity_obj.get("content")
            registry = entity_obj.get("registry")

            dbentity = create_entity(ids, parent_id, additional_metadata, field_id, self_id, link_id, locale_id,
                                     filename, content, registry, request, False)

            dbentities_list.append(dbentity)

        DBSession.bulk_save_objects(dbentities_list)
        DBSession.flush()
        for dbentity in dbentities_list:
            entity =  Entity(id=[dbentity.client_id, dbentity.object_id])
            entity.dbObject = dbentity
            entities.append(entity)
        return BulkCreateEntity(entities=entities, triumph=True)


class UpdateEntityContent(graphene.Mutation):
    """


		mutation My {
	update_entity_content(id:[1907,10], content: "cat"){
		entity{
			created_at
		}
	}
}
    """

    class Arguments:
        """
        input values from request. Look at "LD methods" exel table
        """
        id = LingvodocID()
        content = graphene.String()


    entity = graphene.Field(Entity)
    triumph = graphene.Boolean()

    @staticmethod
    def mutate(root, info, **args):
        # delete
        client_id, object_id = args.get('id')
        content = args.get("content")
        dbentity_old = DBSession.query(dbEntity).filter_by(client_id=client_id, object_id=object_id).first()
        if not dbentity_old or dbentity_old.marked_for_deletion:
            raise ResponseError(message="No such entity in the system")
        if dbentity_old.field.data_type != "Text":
            raise ResponseError(message="Can't edit non-text entities")
        lexical_entry = dbentity_old.parent
        info.context.acl_check('delete', 'lexical_entries_and_entities',
                               (lexical_entry.parent_client_id, lexical_entry.parent_object_id))

        settings = info.context["request"].registry.settings
        if 'desktop' in settings:
            real_delete_entity(dbentity_old, settings)
        else:
            del_object(dbentity_old)
        # create
        client = DBSession.query(Client).filter_by(id=client_id).first()
        user = DBSession.query(dbUser).filter_by(id=client.user_id).first()
        if not user:
            raise ResponseError(message="This client id is orphaned. Try to logout and then login once more.")

        parent = DBSession.query(dbLexicalEntry).filter_by(client_id=dbentity_old.parent_client_id,
                                                           object_id=dbentity_old.parent_object_id).first()
        if not parent:
            raise ResponseError(message="No such lexical entry in the system")

        info.context.acl_check('create', 'lexical_entries_and_entities',
                               (parent.parent_client_id, parent.parent_object_id))
        dbentity = dbEntity(client_id=client_id,
                        object_id=None,
                        field_client_id=dbentity_old.field_client_id,
                        field_object_id=dbentity_old.field_object_id,
                        locale_id=dbentity_old.locale_id,
                        additional_metadata=dbentity_old.additional_metadata,
                        parent=dbentity_old.parent)

        dbentity.publishingentity.accepted = dbentity_old.publishingentity.accepted
        dbentity.content = content
            # if args.get('is_translatable', None): # TODO: fix it
            #     field.is_translatable = bool(args['is_translatable'])
        DBSession.add(dbentity)
        DBSession.flush()
        entity = Entity(id = [dbentity.client_id, dbentity.object_id])
        entity.dbObject = dbentity
        return UpdateEntityContent(entity=entity, triumph=True)
