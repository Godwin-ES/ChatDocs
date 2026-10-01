"""Background document ingestion: parse, chunk, embed and index uploads off the request path.

Uploads return as soon as the original file is safely in GCS. A small worker pool then
indexes it and records the outcome on the file's MongoDB row as `status`:
"processing" -> "ready" (with `chunks`) or "failed" (with a user-facing `error`).
"""
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from app.config import INGEST_WORKERS
from app.storage import download_from_gcs
from app.utils import files_collection, get_vector_db, read_chunks
from app.vector_store import INDEX_VERSION

logger = logging.getLogger("rag-app")

_executor = ThreadPoolExecutor(max_workers=INGEST_WORKERS, thread_name_prefix="ingest")
# Serialises jobs for the same file, e.g. when it is re-uploaded while still indexing.
_file_locks = defaultdict(threading.Lock)
_file_locks_guard = threading.Lock()


def _lock_for(user_id: str, filename: str) -> threading.Lock:
    with _file_locks_guard:
        return _file_locks[(user_id, filename)]


def _set_status(user_id: str, filename: str, **fields):
    return files_collection.update_one({"user_id": user_id, "filename": filename}, {"$set": fields})


def enqueue(user_id: str, filename: str, data: Optional[bytes] = None):
    """Schedules indexing. Without `data`, the file is read back from GCS."""
    return _executor.submit(ingest, user_id, filename, data)


def ingest(user_id: str, filename: str, data: Optional[bytes] = None) -> None:
    with _lock_for(user_id, filename):
        store = get_vector_db(user_id)
        try:
            if data is None:
                data = download_from_gcs(filename, user_id)
            chunks = read_chunks(data, filename)
            count = store.index_document(filename, chunks)
        except Exception:
            logger.exception("Indexing failed for %s", filename)
            _set_status(user_id, filename, status="failed", error="Could not read this file. It may be corrupted or password-protected.")
            return

        if count == 0:
            _set_status(user_id, filename, status="failed",
                        error="No readable text found. The file may be empty, damaged, or scanned images without OCR.")
            return

        result = _set_status(user_id, filename, status="ready", error=None, chunks=count,
                             index_version=INDEX_VERSION, indexed_at=datetime.now(timezone.utc))
        if result.matched_count == 0:
            # The document was deleted while it was being indexed; don't leave orphaned chunks.
            store.delete_document(filename)
        logger.info("Indexed %s (%d chunks)", filename, count)


def resume_pending() -> int:
    """Re-queues files left in "processing" by a restart. Returns how many were queued."""
    pending = list(files_collection.find({"status": "processing"}, {"user_id": 1, "filename": 1}))
    for row in pending:
        enqueue(row["user_id"], row["filename"])
    return len(pending)


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
