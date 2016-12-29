from lingvodoc.scripts.dictionary_dialeqt_converter import convert_all
from lingvodoc.queue.celery import celery
@celery.task
def async_convert_dictionary_new(blob_client_id,
                                 blob_object_id,
                                 client_id,
                                 language_client_id,
                                 language_object_id,
                                 gist_client_id,
                                 gist_object_id,
                                 sqlalchemy_url,
                                 storage,
                                 locale_id,
                                 task_key,
                                 cache_kwargs):

    convert_all(blob_client_id,
                blob_object_id,
                language_client_id,
                language_object_id,
                client_id,
                gist_client_id,
                gist_object_id,
                sqlalchemy_url,
                storage,
                locale_id,
                task_key,
                cache_kwargs
                )
    return
