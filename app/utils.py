import os
import logging
from datetime import datetime, timezone
from functools import cache
from io import BytesIO
from typing import List
from agno.knowledge.document import Document
from agno.knowledge.embedder.huggingface import HuggingfaceCustomEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docx_reader import DocxReader
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.knowledge.chunking.recursive import RecursiveChunking
from pymongo import MongoClient
from pinecone import Pinecone
from pinecone.exceptions import NotFoundException
from app.config import (
    PINECONE_API_KEY, PINECONE_INDEX, MONGO_URL, MONGO_DB_NAME, MONGO_COLL, HF_API_KEY,
    HYBRID_SEARCH, HYBRID_ALPHA,
)
from app.storage import upload_to_gcs, delete_from_gcs, delete_all_from_gcs
from app.vector_store import DocumentStore, Embeddings, SparseEncoder

logger = logging.getLogger("rag-app")

EMBEDDING_DIMENSIONS = 1024

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX)

hf_emb = HuggingfaceCustomEmbedder(dimensions=EMBEDDING_DIMENSIONS, api_key=HF_API_KEY)
embeddings = Embeddings(hf_emb, EMBEDDING_DIMENSIONS)
sparse_encoder = SparseEncoder()

client = MongoClient(MONGO_URL)
db = client.get_database(MONGO_DB_NAME)
files_collection = db.get_collection(MONGO_COLL)

@cache
def hybrid_enabled() -> bool:
    """Hybrid (dense + keyword) search needs a Pinecone index created with the dotproduct metric."""
    if HYBRID_SEARCH == "false":
        return False
    try:
        metric = pc.describe_index(PINECONE_INDEX).metric
    except Exception:
        logger.warning("Could not read the Pinecone index metric; hybrid search disabled", exc_info=True)
        return False
    if metric == "dotproduct":
        return True
    if HYBRID_SEARCH == "true":
        logger.warning("HYBRID_SEARCH=true requires a dotproduct index, but %s uses %s", PINECONE_INDEX, metric)
    return False

def get_vector_db(user_id) -> DocumentStore:
    return DocumentStore(
        index=index,
        embeddings=embeddings,
        sparse=sparse_encoder if hybrid_enabled() else None,
        hybrid_alpha=HYBRID_ALPHA,
        namespace=user_id,
        name=PINECONE_INDEX,
        dimension=EMBEDDING_DIMENSIONS,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
        api_key=PINECONE_API_KEY,
    )

def get_knowledge_base(user_id):
    vector_db = get_vector_db(user_id)
    knowledge = Knowledge(vector_db=vector_db, contents_db=None, max_results=5)
    return knowledge

def get_reader(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf": return PDFReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))
    if ext == ".docx": return DocxReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))
    return TextReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))

def _decode_text(data: bytes) -> bytes:
    """Agno's TextReader only accepts UTF-8; re-encode files saved in other common encodings."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding).encode("utf-8")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").encode("utf-8")

def read_chunks(file_bytes: bytes, filename: str) -> List[Document]:
    """Parses a file from memory into chunks, without touching disk or GCS."""
    if os.path.splitext(filename)[1].lower() in (".txt", ".md"):
        file_bytes = _decode_text(file_bytes)
    return get_reader(filename).read(BytesIO(file_bytes), name=filename)

def store_upload(file_bytes: bytes, filename: str, user_id: str):
    """Saves the original file and records it as processing; indexing happens in app.ingest."""
    upload_to_gcs(file_bytes, filename, user_id)
    # Re-uploading a file replaces it instead of listing it twice.
    files_collection.update_one(
        {"user_id": user_id, "filename": filename},
        {"$set": {"size": len(file_bytes), "uploaded_at": datetime.now(timezone.utc),
                  "status": "processing", "error": None}},
        upsert=True,
    )

def list_document_names(user_id: str, status: str = "ready"):
    return [doc["filename"] for doc in list_documents(user_id) if doc["status"] == status]

def list_documents(user_id: str):
    cursor = files_collection.find({"user_id": user_id}, {"_id": 0}).sort("uploaded_at", -1)
    seen, docs = set(), []
    for doc in cursor:
        if doc["filename"] in seen:  # rows duplicated before uploads were upserted
            continue
        seen.add(doc["filename"])
        uploaded_at = doc.get("uploaded_at")
        docs.append({
            "filename": doc["filename"],
            "size": doc.get("size"),
            "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
            # Rows written before background ingestion have no status and were indexed synchronously.
            "status": doc.get("status", "ready"),
            "error": doc.get("error"),
            "chunks": doc.get("chunks"),
        })
    return docs

def delete_document(filename: str, user_id: str):
    get_vector_db(user_id).delete_document(filename)
    files_collection.delete_many({"user_id": user_id, "filename": filename})
    delete_from_gcs(filename, user_id)

def delete_all_documents(user_id: str):
    try:
        index.delete(delete_all=True, namespace=user_id)
    except NotFoundException:
        pass  # the user never had any vectors
    files_collection.delete_many({"user_id": user_id})
    delete_all_from_gcs(user_id)
