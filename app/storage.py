"""Google Cloud Storage helpers for per-user document storage."""
from functools import cache
from google.api_core.exceptions import NotFound
from google.cloud import storage
from google.oauth2 import service_account
from app.config import GCS_BUCKET_NAME, GCS_CREDENTIALS_JSON


@cache
def _get_bucket() -> storage.Bucket:
    credentials = service_account.Credentials.from_service_account_info(GCS_CREDENTIALS_JSON)
    return storage.Client(credentials=credentials, project=credentials.project_id).bucket(GCS_BUCKET_NAME)


def gcs_path(filename: str, user_id: str) -> str:
    """Returns the GCS object path: {user_id}/{filename}"""
    return f"{user_id}/{filename}"


def upload_to_gcs(file_bytes: bytes, filename: str, user_id: str) -> str:
    """Upload raw bytes to GCS under the user's prefix. Returns the blob path."""
    _get_bucket().blob(gcs_path(filename, user_id)).upload_from_string(file_bytes)
    return gcs_path(filename, user_id)


def download_from_gcs(filename: str, user_id: str) -> bytes:
    """Download a stored file's bytes."""
    return _get_bucket().blob(gcs_path(filename, user_id)).download_as_bytes()


def delete_from_gcs(filename: str, user_id: str) -> None:
    """Delete a single file from GCS. Missing files are ignored."""
    try:
        _get_bucket().blob(gcs_path(filename, user_id)).delete()
    except NotFound:
        pass


def delete_all_from_gcs(user_id: str) -> None:
    """Delete all files under a user's GCS prefix."""
    bucket = _get_bucket()
    blobs = list(bucket.list_blobs(prefix=f"{user_id}/"))
    if blobs:
        bucket.delete_blobs(blobs, on_error=lambda blob: None)
