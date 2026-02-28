import os
from typing import Any, Dict, Optional
from agno.vectordb.pineconedb import PineconeDb
from agno.knowledge.embedder.huggingface import HuggingfaceCustomEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docx_reader import DocxReader
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.utils import strip_agno_metadata
from agno.knowledge.remote_content.remote_content import GCSContent
from pymongo import MongoClient
from pinecone import Pinecone
from app.config import PINECONE_API_KEY, PINECONE_INDEX, MONGO_URL, MONGO_DB_NAME, MONGO_COLL, HF_API_KEY, GCS_BUCKET_NAME
from app.storage import upload_to_gcs, delete_from_gcs, delete_all_from_gcs, gcs_path

# --- Pinecone compatibility patch ---
# Pinecone does not support nested dicts as metadata values.
# Agno's default _merge_metadata stores provider info under a nested '_agno' key,
# which causes insert failures. This patch flattens those keys with an 'agno_' prefix.
def _flat_merge_metadata(
    self,
    provider_metadata: Dict[str, str],
    user_metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = strip_agno_metadata(user_metadata) or {}
    for key, value in provider_metadata.items():
        merged[f"agno_{key}"] = value
    return merged

BaseLoader._merge_metadata = _flat_merge_metadata
# ------------------------------------

pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX)

hf_emb = HuggingfaceCustomEmbedder(dimensions=1024, api_key=HF_API_KEY)

client = MongoClient(MONGO_URL)
db = client.get_database(MONGO_DB_NAME)
files_collection = db.get_collection(MONGO_COLL)

def get_vector_db(user_id):
    vector_db = PineconeDb(
        name=PINECONE_INDEX,
        dimension=1024,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
        api_key=PINECONE_API_KEY,
        embedder=hf_emb,
        namespace=user_id
    )
    return vector_db

def get_knowledge_base(user_id):
    vector_db = get_vector_db(user_id)
    knowledge = Knowledge(vector_db=vector_db, contents_db=None, max_results=5)
    return knowledge

def get_reader(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf": return PDFReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))
    if ext == ".docx": return DocxReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))
    return TextReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))

def process_files(file_bytes: bytes, filename: str, user_id: str):
    # 1. Upload bytes to GCS — the permanent copy, no local disk writes at all
    upload_to_gcs(file_bytes, filename, user_id)

    # 2. Point agno at the GCS object; it downloads → BytesIO internally.
    #    GOOGLE_APPLICATION_CREDENTIALS env var gives agno ADC access automatically.
    gcs_content = GCSContent(
        bucket_name=GCS_BUCKET_NAME,
        blob_name=gcs_path(filename, user_id),  # "{user_id}/{filename}"
    )

    knowledge = get_knowledge_base(user_id)
    knowledge.insert(
        name=filename,
        remote_content=gcs_content,
        reader=get_reader(filename),
    )
    files_collection.insert_one({"user_id": user_id, "filename": filename})

def list_document_names(user_id: str):
    cursor = files_collection.find({"user_id": user_id})
    return [doc["filename"] for doc in cursor]

def delete_document(filename: str, user_id: str):
    index.delete(filter={"name": {"$eq": filename}}, namespace=user_id)
    files_collection.delete_one({"user_id": user_id, "filename": filename})
    delete_from_gcs(filename, user_id)

def delete_all_documents(user_id: str):
    index.delete(delete_all=True, namespace=user_id)
    files_collection.delete_many({"user_id": user_id})
    delete_all_from_gcs(user_id)