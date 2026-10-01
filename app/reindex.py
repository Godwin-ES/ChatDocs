"""Re-index stored documents from their original files in GCS.

Run after upgrading the embedding pipeline, or after pointing PINECONE_INDEX at a new
index (for example a dotproduct index to enable hybrid search):

    python -m app.reindex              # documents indexed with an older pipeline
    python -m app.reindex --all        # every document (use after switching indexes)
    python -m app.reindex --user <id>  # limit to one user
    python -m app.reindex --dry-run    # list what would be re-indexed
"""
import argparse
import logging
import time

from app.ingest import ingest
from app.utils import files_collection, hybrid_enabled
from app.vector_store import INDEX_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="re-index every document, not only outdated ones")
    parser.add_argument("--user", help="only re-index this user's documents")
    parser.add_argument("--dry-run", action="store_true", help="list documents without re-indexing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    query = {} if args.all else {
        "status": {"$ne": "failed"},  # failed uploads are retried from the UI instead
        "$or": [{"index_version": {"$exists": False}}, {"index_version": {"$lt": INDEX_VERSION}}],
    }
    if args.user:
        query["user_id"] = args.user
    rows = list(files_collection.find(query, {"user_id": 1, "filename": 1}))
    print(f"{len(rows)} document(s) to re-index (hybrid search: {'on' if hybrid_enabled() else 'off'})")

    failed = 0
    for n, row in enumerate(rows, 1):
        user_id, filename = row["user_id"], row["filename"]
        print(f"[{n}/{len(rows)}] {user_id}/{filename}", end=" ", flush=True)
        if args.dry_run:
            print()
            continue
        start = time.perf_counter()
        files_collection.update_one({"_id": row["_id"]}, {"$set": {"status": "processing", "error": None}})
        ingest(user_id, filename)
        status = files_collection.find_one({"_id": row["_id"]}, {"status": 1, "chunks": 1, "error": 1}) or {}
        if status.get("status") == "ready":
            print(f"ok, {status.get('chunks')} chunks in {time.perf_counter() - start:.1f}s")
        else:
            failed += 1
            print(f"FAILED: {status.get('error')}")

    if failed:
        print(f"{failed} document(s) failed; see the log above.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
