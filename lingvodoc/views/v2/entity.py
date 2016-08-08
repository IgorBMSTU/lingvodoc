# __author__ = 'alexander'
#
# from lingvodoc.exceptions import CommonException
# from lingvodoc.views.v2.utils import (
#     create_object
# )
# from lingvodoc.models import (
#     Client,
#     DBSession,
#     Entity,
#     LexicalEntry,
#     User
# )
#
# from pyramid.httpexceptions import (
#     HTTPConflict,
#     HTTPInternalServerError,
#     HTTPNotFound,
#     HTTPOk
# )
# from pyramid.security import authenticated_userid
# from pyramid.view import view_config
#
# from sqlalchemy.exc import IntegrityError
#
# import base64
# import hashlib
# import json
#
# @view_config(route_name='get_entity_indict', renderer='json', request_method='GET', permission='view')
# @view_config(route_name='get_entity', renderer='json', request_method='GET', permission='view')
# def view_entity(request):
#     response = dict()
#     client_id = request.matchdict.get('client_id')
#     object_id = request.matchdict.get('object_id')
#     entity = DBSession.query(Entity).filter_by(client_id=client_id, object_id=object_id).first()
#     if entity and not entity.marked_for_deletion:
#         # TODO: fix urls to relative urls in content
#         response = entity.track(False)
#         request.response.status = HTTPOk.code
#         return response
#     request.response.status = HTTPNotFound.code
#     return {'error': str("No such entity in the system")}
#
#
# @view_config(route_name='get_entity_indict', renderer='json', request_method='DELETE', permission='delete')
# @view_config(route_name='get_entity', renderer='json', request_method='DELETE', permission='delete')
# def delete_entity(request):
#     response = dict()
#     client_id = request.matchdict.get('client_id')
#     object_id = request.matchdict.get('object_id')
#     entity = DBSession.query(Entity).filter_by(client_id=client_id, object_id=object_id).first()
#     if entity and not entity.marked_for_deletion:
#         entity.marked_for_deletion = True
#         request.response.status = HTTPOk.code
#         return response
#     request.response.status = HTTPNotFound.code
#     return {'error': str("No such entity in the system")}
#
#
# @view_config(route_name='create_entity', renderer='json', request_method='POST', permission='create')
# def create_entity(request):  # tested
#     try:
#         variables = {'auth': authenticated_userid(request)}
#         response = dict()
#         parent_client_id = request.matchdict.get('lexical_entry_client_id')
#         parent_object_id = request.matchdict.get('lexical_entry_object_id')
#         req = request.json_body
#         client = DBSession.query(Client).filter_by(id=variables['auth']).first()
#         if not client:
#             raise KeyError("Invalid client id (not registered on server). Try to logout and then login.")
#         user = DBSession.query(User).filter_by(id=client.user_id).first()
#         if not user:
#             raise CommonException("This client id is orphaned. Try to logout and then login once more.")
#
#         parent = DBSession.query(LexicalEntry).filter_by(client_id=parent_client_id, object_id=parent_object_id).first()
#         if not parent:
#             request.response.status = HTTPNotFound.code
#             return {'error': str("No such lexical entry in the system")}
#         additional_metadata = req.get('additional_metadata')
#         parent_entity = None
#         if req.get('entity_client_id') and req.get('entity_object_id'):
#             parent_entity = DBSession.query(Entity).filter_by(client_id=req['entity_client_id'],
#                                                               object_id=req['entity_object_id']).first()
#             if not parent_entity:
#                 return {'error': str("No such parent entity in the system")}
#         entity = Entity(client_id=client.id,
#                         field_client_id=req['field_client_id'],
#                         field_object_id=req['field_object_id'],
#                         locale_id=req['locale_id'],
#                         additional_metadata=additional_metadata,
#                         parent=parent)
#         if parent_entity:
#             entity.parent_entity=parent_entity
#         DBSession.add(entity)
#         DBSession.flush()
#         data_type = req.get('data_type')
#         filename = req.get('filename')
#         real_location = None
#         url = None
#         if data_type == 'image' or data_type == 'sound' or data_type == 'markup':
#             real_location, url = create_object(request, req['content'], entity, data_type, filename)
#
#         if url and real_location:
#             entity.content = url
#             old_meta = entity.additional_metadata
#
#             need_hash = True
#             if old_meta:
#                 new_meta=json.loads(old_meta)
#                 if new_meta.get('hash'):
#                     need_hash = False
#             if need_hash:
#                 hash = hashlib.sha224(base64.urlsafe_b64decode(req['content'])).hexdigest()
#                 hash_dict = {'hash': hash}
#                 if old_meta:
#                     new_meta = json.loads(old_meta)
#                     new_meta.update(hash_dict)
#                 else:
#                     new_meta = hash_dict
#                 entity.additional_metadata = json.dumps(new_meta)
#         else:
#             entity.content = req['content']
#         DBSession.add(entity)
#         request.response.status = HTTPOk.code
#         response['client_id'] = entity.client_id
#         response['object_id'] = entity.object_id
#         return response
#
#     except IntegrityError as e:
#         request.response.status = HTTPInternalServerError.code
#         return {'error': str(e)}
#
#     except CommonException as e:
#         request.response.status = HTTPConflict.code
#         return {'error': str(e)}