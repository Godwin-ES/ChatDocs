"""Google Cloud Storage helpers for per-user document storage."""
from google.cloud import storage
from google.oauth2 import service_account
from app.config import GCS_BUCKET_NAME, GCS_CREDENTIALS_JSON


def _get_client() -> storage.Client:
    credentials = service_account.Credentials.from_service_account_info(GCS_CREDENTIALS_JSON)
    return storage.Client(credentials=credentials)


def gcs_path(filename: str, user_id: str) -> str:
    """Returns the GCS object path: {user_id}/{filename}"""
    return f"{user_id}/{filename}"


def upload_to_gcs(file_bytes: bytes, filename: str, user_id: str) -> str:
    """Upload raw bytes to GCS under the user's prefix. Returns the blob path."""
    client = _get_client()
    blob = client.bucket(GCS_BUCKET_NAME).blob(gcs_path(filename, user_id))
    blob.upload_from_string(file_bytes)
    return gcs_path(filename, user_id)


def delete_from_gcs(filename: str, user_id: str) -> None:
    """Delete a single file from GCS."""
    client = _get_client()
    client.bucket(GCS_BUCKET_NAME).blob(gcs_path(filename, user_id)).delete()


def delete_all_from_gcs(user_id: str) -> None:
    """Delete all files under a user's GCS prefix."""
    client = _get_client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=f"{user_id}/"))
    if blobs:
        bucket.delete_blobs(blobs)
