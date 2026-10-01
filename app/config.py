"""Configuration settings for the Agentic RAG API"""
import os
import json
from dotenv import load_dotenv, find_dotenv

# Load environment variables
load_dotenv(find_dotenv())


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# Model configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_URL = os.getenv("GROQ_URL", "https://api.groq.com/openai/v1")

HF_API_KEY = os.getenv("HF_API_KEY")

# Database configuration
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")
MONGO_URL = os.getenv("MONGO_URL")
MONGO_COLL = os.getenv("MONGO_COLL")

#Pinecone configuration
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
# Hybrid (semantic + keyword) search: "auto" turns it on when the index uses the
# dotproduct metric, which Pinecone requires for sparse vectors.
HYBRID_SEARCH = os.getenv("HYBRID_SEARCH", "auto").lower()
# Weight of semantic vs keyword matching in hybrid search (1.0 = semantic only).
HYBRID_ALPHA = float(os.getenv("HYBRID_ALPHA", "0.75"))

# Number of documents indexed in parallel in the background
INGEST_WORKERS = int(os.getenv("INGEST_WORKERS", "2"))

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Comma-separated list of extra origins allowed to call the API with cookies.
# The bundled frontend is served from the same origin and needs no entry here.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Upload limits
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# --- Authentication Configuration ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
SECRET_KEY = _require("SECRET_KEY")

# Secure cookies and strict HTTPS OAuth are used whenever the app is served over HTTPS.
# Set COOKIE_SECURE explicitly to override the detection.
_https = GOOGLE_REDIRECT_URI.startswith("https://")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", str(_https)).lower() in ("1", "true", "yes")
SESSION_MAX_AGE = 3600 * 24

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
try:
    GCS_CREDENTIALS_JSON = json.loads(_require("GCS_CREDENTIALS_JSON"))
except json.JSONDecodeError as e:
    raise RuntimeError("GCS_CREDENTIALS_JSON must be the service account key as inline JSON") from e
