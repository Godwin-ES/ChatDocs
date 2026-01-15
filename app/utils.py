import os
from agno.vectordb.pineconedb import PineconeDb
from agno.knowledge.embedder.huggingface import HuggingfaceCustomEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docx_reader import DocxReader
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.knowledge.chunking.recursive import RecursiveChunking
from pymongo import MongoClient
from pinecone import Pinecone
from app.config import PINECONE_API_KEY, PINECONE_INDEX, MONGO_URL, MONGO_DB_NAME, MONGO_COLL, HF_API_KEY

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

def get_reader(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf": return PDFReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))
    if ext == ".docx": return DocxReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100))
    return TextReader(chunking_strategy=RecursiveChunking(chunk_size=1000, overlap=100)) 

def process_files(file_path, filename, user_id):
    reader = get_reader(file_path)
    knowledge = get_knowledge_base(user_id)
    knowledge.add_content(path=file_path, reader=reader, name=filename)
    files_collection.insert_one({"user_id": user_id, "filename": filename})

def list_document_names(user_id):
    cursor = files_collection.find({"user_id": user_id})
    return [doc["filename"] for doc in cursor]

def delete_document(filename, user_id):
    index.delete(filter={"name": {"$eq": filename}}, namespace=user_id)
    files_collection.delete_one({"user_id": user_id, "filename": filename})

def delete_all_documents(user_id):
    index.delete(delete_all=True, namespace=user_id)
    files_collection.delete_many({"user_id": user_id})