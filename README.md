# ChatDocs

A production-ready Retrieval-Augmented Generation (RAG) API built with FastAPI, featuring Google OAuth authentication, multi-user document management, persistent Google Cloud Storage, and intelligent AI-powered question-answering capabilities.

## 🌟 Features

- **🔐 Google OAuth Authentication**: Secure user authentication with Google SSO
- **📄 Multi-Format Document Support**: Upload and process PDF, DOCX, and TXT files
- **🧠 Intelligent RAG**: AI-powered question-answering using your uploaded documents
- **💾 Multi-User Support**: Isolated document storage per user across all layers (GCS, Pinecone, MongoDB)
- **☁️ Persistent Document Storage**: Uploaded files are stored permanently in Google Cloud Storage — no temporary files or local disk writes
- **🔍 Vector Search**: Powered by Pinecone for fast semantic search
- **💬 Session Management**: Conversation history with MongoDB
- **📊 Agentic Memory**: Context-aware conversations with session summaries
- **🌐 CORS Enabled**: Ready for frontend integration
- **⚡ Streaming Responses**: Real-time AI responses

## 🏗️ Architecture

- **FastAPI**: Modern, high-performance web framework
- **Agno Framework**: Agentic AI framework for RAG implementation
- **Google Cloud Storage**: Persistent per-user document storage (`{user_id}/{filename}`)
- **Pinecone**: Vector database for document embeddings (namespaced per user)
- **MongoDB**: User data, conversation history, and file metadata (filtered per user)
- **HuggingFace**: Custom embeddings (1024 dimensions)
- **OpenAI-compatible API**: Groq integration for LLM inference

### Upload Flow
```
POST /upload  (returns 202 as soon as the file is saved)
    │
    ├──► Store bytes in GCS: {user_id}/{filename}   (permanent, no temp file)
    ├──► Save metadata → MongoDB with status "processing"
    └──► Background worker (app/ingest.py)
            ├──► Parse + chunk from memory
            ├──► Batch-embed chunks ("passage: " prefix for e5)
            ├──► Upsert → Pinecone (namespace: user_id, ids "<doc key>#<n>")
            └──► MongoDB status → "ready" (or "failed" with a reason)
```
The UI polls `/documents` while anything is processing. Files still "processing" when the
server stops are re-queued from GCS on the next start.

### Isolation Per Layer
| Layer | Strategy |
|-------|----------|
| GCS | `{user_id}/{filename}` prefix |
| Pinecone | `namespace = user_id` |
| MongoDB | `user_id` field filter |

## 📋 Prerequisites

- Python >= 3.13
- MongoDB instance
- Pinecone account and API key
- Google OAuth credentials (for user login)
- Google Cloud Storage bucket + Service Account with `Storage Object Admin` role
- HuggingFace API key
- Groq API key (or OpenAI-compatible endpoint)

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Godwin-ES/ChatDocs.git
   cd ChatDocs
   ```

2. **Install dependencies using uv (recommended)**
   ```bash
   pip install uv
   uv sync
   ```

   Or with pip:
   ```bash
   pip install -e .
   ```

3. **Set up environment variables**

   Create a `.env` file in the root directory:
   ```env
   # Model Configuration
   GROQ_API_KEY=your_groq_api_key
   GROQ_MODEL=openai/gpt-oss-20b
   GROQ_URL=https://api.groq.com/openai/v1

   # HuggingFace
   HF_API_KEY=your_huggingface_api_key

   # Database Configuration
   MONGO_URL=mongodb://localhost:27017
   MONGO_DB_NAME=rag-db
   MONGO_COLL=user_files

   # Pinecone Configuration
   PINECONE_API_KEY=your_pinecone_api_key
   PINECONE_INDEX=your_index_name

   # Server Configuration
   HOST=0.0.0.0
   PORT=8000

   # Google OAuth (user login)
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
   SECRET_KEY=your_secret_key_for_sessions

   # Optional
   ALLOWED_ORIGINS=https://your-frontend.example.com  # only needed for a frontend on another origin
   MAX_UPLOAD_MB=20
   COOKIE_SECURE=true  # defaults to true when GOOGLE_REDIRECT_URI is https

   # Google Cloud Storage (document storage)
   GCS_BUCKET_NAME=your_gcs_bucket_name
   GCS_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}  # inline service account JSON

   # Retrieval & ingestion (optional)
   HYBRID_SEARCH=auto   # auto | true | false; auto enables it on dotproduct indexes
   HYBRID_ALPHA=0.75    # 1.0 = semantic only, 0.0 = keyword only
   INGEST_WORKERS=2     # documents indexed in parallel
   ```

   > **GCS setup**: Create a bucket, create a Service Account with the `Storage Object Admin` role scoped to that bucket, download the JSON key, and set `GCS_CREDENTIALS_JSON` to its contents as inline JSON.

4. **Run the application**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

## 📚 API Endpoints

### Authentication

- **GET** `/auth/login` - Initiate Google OAuth login
- **GET** `/auth/callback` - OAuth callback handler
- **GET** `/auth/logout` - Logout and clear session
- **GET** `/auth/me` - Get current user information

### RAG Operations

- **POST** `/chat` - Chat with your documents
  ```json
  {
    "message": "What is the main topic of the document?",
    "thread_id": "optional-thread-id"
  }
  ```
  Streams newline-delimited JSON (`application/x-ndjson`); the thread id is returned in the `X-Thread-ID` header:
  ```
  {"type": "status", "text": "Searching your documents", "detail": "main topic"}
  {"type": "sources", "items": [{"name": "report.pdf", "page": 3}]}
  {"type": "delta", "text": "The document..."}
  {"type": "done"}
  ```

### Conversations

- **GET** `/threads` - List the current user's conversations (newest first)
- **GET** `/threads/{thread_id}` - Get a conversation's messages, with sources
- **DELETE** `/threads/{thread_id}` - Delete a conversation

### Document Management

- **POST** `/upload` - Upload documents (PDF, DOCX, TXT, MD; up to `MAX_UPLOAD_MB` each)
  - Multipart form-data with `files` field
  - Files are stored in GCS and indexed into Pinecone — no local disk writes
  - Returns a per-file `results` list (`{"filename", "ok", "error"}`); re-uploading a filename replaces it

- **GET** `/documents` - List the current user's documents as `{"filename", "size", "uploaded_at", "status", "error", "chunks"}` objects; `status` is `processing`, `ready` or `failed`

- **POST** `/documents/retry` - Re-index a failed document from its stored file
  ```json
  { "filename": "example.pdf" }
  ```

- **DELETE** `/delete-document` - Delete a specific document from GCS, Pinecone, and MongoDB
  ```json
  {
    "filename": "example.pdf"
  }
  ```

- **DELETE** `/clear-knowledge` - Delete all documents for the current user from all three stores

## 🎯 Usage Example

### 1. Login
Navigate to `http://localhost:8000/auth/login` to authenticate with Google.

### 2. Upload Documents
```bash
curl -X POST "http://localhost:8000/upload" \
  -H "Cookie: session_token=YOUR_TOKEN" \
  -F "files=@document.pdf"
```

### 3. Chat with Documents
```bash
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_TOKEN" \
  -d '{
    "message": "Summarize the key points from my documents",
    "thread_id": "conversation-1"
  }'
```

### 4. List Documents
```bash
curl -X GET "http://localhost:8000/documents" \
  -H "Cookie: session_token=YOUR_TOKEN"
```

### 5. Delete a Document
```bash
curl -X DELETE "http://localhost:8000/delete-document" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_TOKEN" \
  -d '{"filename": "document.pdf"}'
```

## 🧩 Project Structure

```
ChatDocs/
├── app/
│   ├── main.py          # FastAPI application and routes
│   ├── agent.py         # RAG agent configuration
│   ├── utils.py         # Document processing and knowledge base
│   ├── storage.py       # Google Cloud Storage helpers
│   ├── config.py        # Configuration and env var loading
│   ├── prompts.py       # AI agent instructions
│   └── static/
│       └── index.html   # Frontend
├── pyproject.toml       # Project dependencies
├── .gitignore
└── README.md
```

## 🔧 Configuration

### Document Processing
- **Chunk Size**: 1000 characters
- **Chunk Overlap**: 100 characters
- **Embedding Dimensions**: 1024
- **Max Search Results**: 5

### Vector Database
- **Provider**: Pinecone
- **Metric**: Cosine similarity (dotproduct enables hybrid search)
- **Cloud**: AWS (us-east-1)
- **Embeddings**: `intfloat/multilingual-e5-large`, batch-embedded and L2-normalised, with the
  `query: ` / `passage: ` prefixes the model was trained with

### Re-indexing
Chunks embedded before the e5 prefixes were added should be re-indexed once. Originals are
re-read from GCS, so nothing needs re-uploading:
```bash
python -m app.reindex --dry-run   # see what will be re-indexed
python -m app.reindex             # re-index outdated documents
```

### Enabling hybrid search
Hybrid search adds BM25 keyword matching, which helps with names, codes and numbers. Pinecone
only supports it on indexes created with the **dotproduct** metric:
1. Create a new serverless index: 1024 dimensions, metric `dotproduct`.
2. Point `PINECONE_INDEX` at it and restart. With `HYBRID_SEARCH=auto` it turns on by itself.
3. Run `python -m app.reindex --all` to fill the new index from GCS.

### AI Agent Features
- Agentic memory enabled
- Session summaries enabled
- Knowledge search enabled
- Streaming responses enabled

## 🛡️ Security Features

- Session-based authentication with secure cookies
- HTTP-only cookies with 24-hour expiration
- User-isolated storage across GCS, Pinecone, and MongoDB
- Token-based session serialization with `URLSafeTimedSerializer`
- Service account credentials never exposed to clients

## 🚦 Development

### Prerequisites for Development
- Python 3.13+
- MongoDB (local or cloud)
- Pinecone account
- Google Cloud Console project with OAuth 2.0 and a GCS bucket configured

### Running in Development Mode
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 📦 Dependencies

Core dependencies:
- `fastapi` - Web framework
- `agno` - Agentic AI framework
- `pinecone` - Vector database
- `pymongo` - MongoDB driver
- `google-cloud-storage` - GCS document storage
- `openai` - LLM API client
- `huggingface-hub` - Embeddings
- `fastapi-sso` - Google OAuth
- `pypdf` - PDF processing
- `python-docx` - DOCX processing
- `uvicorn` - ASGI server

See `pyproject.toml` for full dependency list.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [Agno Framework](https://github.com/agno-agi/agno)
- Powered by [FastAPI](https://fastapi.tiangolo.com/)
- Vector search by [Pinecone](https://www.pinecone.io/)
- Document storage by [Google Cloud Storage](https://cloud.google.com/storage)

## 📧 Contact

For questions or support, please open an issue on GitHub.

---

**Note**: Keep your API keys and credentials secure. Never commit `.env` files or service account JSON files to version control.
