"""MinIO (S3-compatible) object storage.

Documents are stored under `{tenant_id}/{document_id}/{filename}` so that
object paths themselves are tenant-namespaced.
"""
from functools import lru_cache
from io import BytesIO

from minio import Minio

from app.core.config import settings


@lru_cache
def get_minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket() -> None:
    client = get_minio_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


def upload_bytes(object_name: str, data: bytes, content_type: str) -> str:
    client = get_minio_client()
    client.put_object(
        settings.minio_bucket,
        object_name,
        BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return object_name


def delete_object(object_name: str) -> None:
    client = get_minio_client()
    client.remove_object(settings.minio_bucket, object_name)


def download_bytes(object_name: str) -> bytes:
    client = get_minio_client()
    response = client.get_object(settings.minio_bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
