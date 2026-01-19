# FastAPI RAG

A production-ready Retrieval-Augmented Generation (RAG) API built with FastAPI, featuring Google OAuth authentication, multi-user document management, and intelligent AI-powered question-answering capabilities.

## 🌟 Features

- **🔐 Google OAuth Authentication**: Secure user authentication with Google SSO
- **📄 Multi-Format Document Support**: Upload and process PDF, DOCX, and TXT files
- **🧠 Intelligent RAG**: AI-powered question-answering using your uploaded documents
- **💾 Multi-User Support**: Isolated document storage per user using namespaces
- **🔍 Vector Search**: Powered by Pinecone for fast semantic search
- **💬 Session Management**: Conversation history with MongoDB
- **📊 Agentic Memory**: Context-aware conversations with session summaries
- **🌐 CORS Enabled**: Ready for frontend integration
- **⚡ Streaming Responses**: Real-time AI responses

## 🏗️ Architecture

- **FastAPI**: Modern, high-performance web framework
- **Agno Framework**: Agentic AI framework for RAG implementation
- **Pinecone**: Vector database for document embeddings
- **MongoDB**: User data and conversation history storage
- **HuggingFace**:  Custom embeddings (1024 dimensions)
- **OpenAI-compatible API**: Groq integration for LLM inference

## 📋 Prerequisites

- Python >= 3.13
- MongoDB instance
- Pinecone account and API key
- Google OAuth credentials
- HuggingFace API key
- Groq API key (or OpenAI-compatible endpoint)

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Godwin-ES/fastapi_rag.git
   cd fastapi_rag
   ```

2. **Install dependencies using uv (recommended)**
   ```bash
   pip install uv
   uv pip install -e .
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
   MONGO_DB_NAME=fastapi_rag
   MONGO_COLL=uploaded_files

   # Pinecone Configuration
   PINECONE_API_KEY=your_pinecone_api_key
   PINECONE_INDEX=your_index_name

   # Server Configuration
   HOST=0.0.0.0
   PORT=8000

   # Google OAuth
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
   SECRET_KEY=your_secret_key_for_sessions
   ```

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

### Document Management

- **POST** `/upload` - Upload documents (PDF, DOCX, TXT)
  - Multipart form-data with file(s)
  
- **GET** `/documents` - List all uploaded documents for current user

- **DELETE** `/delete-document` - Delete a specific document
  ```json
  {
    "filename": "example.pdf"
  }
  ```

- **DELETE** `/delete-all` - Delete all documents for current user

## 🎯 Usage Example

### 1. Login
Navigate to `http://localhost:8000/auth/login` to authenticate with Google. 

### 2. Upload Documents
```bash
curl -X POST "http://localhost:8000/upload" \
  -H "Cookie: session_token=YOUR_TOKEN" \
  -F "files=@document. pdf"
```

### 3. Chat with Documents
```bash
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_token=YOUR_TOKEN" \
  -d '{
    "message": "Summarize the key points from my documents",
    "thread_id":  "conversation-1"
  }'
```

### 4. List Documents
```bash
curl -X GET "http://localhost:8000/documents" \
  -H "Cookie:  session_token=YOUR_TOKEN"
```

## 🧩 Project Structure

```
fastapi_rag/
├── app/
│   ├── main.py          # FastAPI application and routes
│   ├── agent. py         # RAG agent configuration
│   ├── utils.py         # Document processing utilities
│   ├── config.py        # Configuration management
│   └── prompts.py       # AI agent instructions
├── pyproject.toml       # Project dependencies
├── . gitignore
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
- **Metric**: Cosine similarity
- **Cloud**: AWS (us-east-1)

### AI Agent Features
- Agentic memory enabled
- Session summaries enabled
- Knowledge search enabled
- Streaming responses enabled

## 🛡️ Security Features

- Session-based authentication with secure cookies
- HTTP-only cookies with 24-hour expiration
- User-isolated namespaces for document storage
- Token-based session serialization with URLSafeTimedSerializer

## 🚦 Development

### Prerequisites for Development
- Python 3.13+
- MongoDB (local or cloud)
- Pinecone account
- Google Cloud Console project with OAuth 2.0 configured

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

## 📧 Contact

For questions or support, please open an issue on GitHub. 

---

**Note**: Make sure to keep your API keys and secrets secure.  Never commit `.env` files to version control.
