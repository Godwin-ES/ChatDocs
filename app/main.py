import os
import json
import uuid
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi_sso.sso.google import GoogleSSO
from itsdangerous import URLSafeTimedSerializer, BadSignature
from agno.db.base import SessionType
from agno.run.agent import RunEvent
from app.agent import get_rag_agent, memory_db
from app.utils import store_upload, delete_document, delete_all_documents, list_documents, files_collection
from app import ingest
from app.config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, SECRET_KEY, HOST, PORT,
    ALLOWED_ORIGINS, COOKIE_SECURE, SESSION_MAX_AGE, MAX_UPLOAD_MB, ALLOWED_EXTENSIONS,
)

logger = logging.getLogger("rag-app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    resumed = ingest.resume_pending()
    if resumed:
        logger.info("Resumed indexing for %d document(s)", resumed)
    yield
    ingest.shutdown()

app = FastAPI(title="Agentic RAG API", lifespan=lifespan)

# --- CORS Configuration ---
# The bundled frontend is same-origin. Cross-origin access with cookies is only
# granted to origins listed explicitly in ALLOWED_ORIGINS.
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Thread-ID"],
    )

google_sso = GoogleSSO(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    redirect_uri=GOOGLE_REDIRECT_URI,
    allow_insecure_http=not COOKIE_SECURE,
)

serializer = URLSafeTimedSerializer(SECRET_KEY)

# --- Pydantic Models ---
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None

class DocumentRequest(BaseModel):
    filename: str

# --- Dependencies ---
def read_session(request: Request) -> Optional[dict]:
    token = request.cookies.get("session_token")
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None

async def get_current_user(request: Request) -> dict:
    session = read_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session

async def get_current_user_id(user: dict = Depends(get_current_user)) -> str:
    return user["user_id"]

# --- Auth Routes ---
@app.get("/auth/login")
async def login():
    return await google_sso.get_login_redirect()

@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        user = await google_sso.verify_and_process(request)
    except Exception:
        logger.exception("Google sign-in failed")
        raise HTTPException(status_code=400, detail="Sign-in failed. Please try again.")
    session_data = {
        "email": user.email,
        "name": user.first_name or user.display_name,
        "picture": user.picture,
        "user_id": user.id,
    }
    token = serializer.dumps(session_data)
    response = RedirectResponse(url="/")
    response.set_cookie(
        key="session_token", value=token, max_age=SESSION_MAX_AGE,
        httponly=True, secure=COOKIE_SECURE, samesite="lax",
    )
    return response

@app.get("/auth/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("session_token", httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return response

@app.get("/auth/me")
async def get_current_user_info(request: Request):
    session = read_session(request)
    if session is None:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return {
        "user_id": session["user_id"],
        "name": session.get("name"),
        "email": session.get("email"),
        "picture": session.get("picture"),
    }

# --- RAG Endpoints ---
STATUS_BY_TOOL = {
    "search_knowledge_base": "Searching your documents",
    "update_user_memory": "Updating memory",
}

def _sources_from_search(result) -> List[dict]:
    """Extracts {name, page} pairs from a search_knowledge_base JSON result."""
    try:
        docs = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        return []
    sources = []
    for doc in docs if isinstance(docs, list) else []:
        if not isinstance(doc, dict):
            continue
        meta = doc.get("meta_data") or {}
        name = doc.get("name") or meta.get("name")
        if not name:
            continue
        page = meta.get("page")
        sources.append({"name": name, "page": int(page) if isinstance(page, (int, float)) else None})
    return sources

def _merge_sources(existing: List[dict], new: List[dict]) -> List[dict]:
    seen = {(s["name"], s["page"]) for s in existing}
    for s in new:
        if (s["name"], s["page"]) not in seen:
            seen.add((s["name"], s["page"]))
            existing.append(s)
    return existing

@app.post("/chat")
def chat_endpoint(request: ChatRequest, user: dict = Depends(get_current_user)):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is empty")
    thread_id = request.thread_id or str(uuid.uuid4())

    # Initialize Agent
    rag_agent = get_rag_agent(user_id=user["user_id"], session_id=thread_id, user_name=user.get("name"))

    # Streams newline-delimited JSON events:
    #   {"type": "status", "text": ...}   the agent is using a tool
    #   {"type": "delta", "text": ...}    a piece of the answer
    #   {"type": "sources", "items": [...]}
    #   {"type": "error", "text": ...}
    #   {"type": "done"}
    def stream_generator():
        def event(**payload):
            return json.dumps(payload) + "\n"

        sources: List[dict] = []
        try:
            for chunk in rag_agent.run(message, stream=True, stream_events=True):
                kind = getattr(chunk, "event", None)
                if kind == RunEvent.run_content and isinstance(chunk.content, str) and chunk.content:
                    yield event(type="delta", text=chunk.content)
                elif kind == RunEvent.tool_call_started and chunk.tool:
                    status = STATUS_BY_TOOL.get(chunk.tool.tool_name, "Working")
                    query = (chunk.tool.tool_args or {}).get("query")
                    yield event(type="status", text=status, detail=query)
                elif kind == RunEvent.tool_call_completed and chunk.tool:
                    if chunk.tool.tool_name == "search_knowledge_base":
                        _merge_sources(sources, _sources_from_search(chunk.tool.result))
                        yield event(type="sources", items=sources)
                elif kind == RunEvent.run_error:
                    logger.error("Agent run error: %s", getattr(chunk, "content", None))
                    yield event(type="error", text="The assistant ran into a problem. Please try again.")
        except Exception:
            logger.exception("Chat stream failed")
            yield event(type="error", text="The assistant ran into a problem. Please try again.")
        yield event(type="done")

    return StreamingResponse(
        stream_generator(),
        media_type="application/x-ndjson",
        headers={"X-Thread-ID": thread_id, "Cache-Control": "no-cache"},
    )

# --- Conversation History ---
def _run_messages(run) -> List[dict]:
    messages = []
    if run.input is not None:
        messages.append({"role": "user", "content": run.input.input_content_string()})
    if isinstance(run.content, str) and run.content:
        sources: List[dict] = []
        for ref in run.references or []:
            _merge_sources(sources, _sources_from_search(ref.references or []))
        messages.append({"role": "assistant", "content": run.content, "sources": sources})
    return messages

def _thread_title(session) -> str:
    for run in session.runs or []:
        if run.input is not None:
            text = " ".join(run.input.input_content_string().split())
            return text[:60] + ("…" if len(text) > 60 else "")
    return "New conversation"

@app.get("/threads")
def list_threads(user_id: str = Depends(get_current_user_id)):
    sessions = memory_db.get_sessions(
        session_type=SessionType.AGENT, user_id=user_id,
        sort_by="updated_at", sort_order="desc", limit=50,
    )
    return {"threads": [
        {"id": s.session_id, "title": _thread_title(s), "updated_at": s.updated_at or s.created_at}
        for s in sessions if s.runs
    ]}

@app.get("/threads/{thread_id}")
def get_thread(thread_id: str, user_id: str = Depends(get_current_user_id)):
    session = memory_db.get_session(session_id=thread_id, session_type=SessionType.AGENT, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = []
    for run in session.runs or []:
        if getattr(run, "parent_run_id", None):
            continue
        messages.extend(_run_messages(run))
    return {"id": thread_id, "title": _thread_title(session), "messages": messages}

@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, user_id: str = Depends(get_current_user_id)):
    memory_db.delete_session(session_id=thread_id, user_id=user_id)
    return {"message": "Conversation deleted"}

# --- Document Endpoints ---
# These are plain `def` so FastAPI runs them in a worker thread: ingestion and
# deletes are blocking calls and must not stall the event loop for other users.
@app.post("/upload")
def upload_documents(files: List[UploadFile] = File(...), user_id: str = Depends(get_current_user_id)):
    results = []
    for file in files:
        filename = os.path.basename(file.filename or "").strip()
        ext = os.path.splitext(filename)[1].lower()
        if not filename or ext not in ALLOWED_EXTENSIONS:
            results.append({"filename": filename or "unnamed", "ok": False,
                            "error": "Unsupported file type. Use PDF, DOCX, TXT or MD."})
            continue
        file_bytes = file.file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(file_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
            results.append({"filename": filename, "ok": False, "error": f"File is larger than {MAX_UPLOAD_MB} MB."})
            continue
        if not file_bytes:
            results.append({"filename": filename, "ok": False, "error": "File is empty."})
            continue
        try:
            store_upload(file_bytes, filename, user_id)
        except Exception:
            logger.exception("Failed to store %s", filename)
            results.append({"filename": filename, "ok": False, "error": "Could not save this file."})
            continue
        # Indexing continues in the background; poll /documents for its status.
        ingest.enqueue(user_id, filename, file_bytes)
        results.append({"filename": filename, "ok": True, "status": "processing"})

    accepted = [r["filename"] for r in results if r["ok"]]
    if not accepted and results:
        return JSONResponse(status_code=422, content={"message": "No files accepted", "results": results})
    return JSONResponse(status_code=202, content={"message": "Accepted", "processed_files": accepted, "results": results})

@app.post("/documents/retry")
def retry_document(request: DocumentRequest, user_id: str = Depends(get_current_user_id)):
    result = files_collection.update_one(
        {"user_id": user_id, "filename": request.filename, "status": "failed"},
        {"$set": {"status": "processing", "error": None}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="No failed document with that name")
    ingest.enqueue(user_id, request.filename)
    return {"message": "Retrying", "filename": request.filename}

@app.delete("/clear-knowledge")
def clear_knowledge_base(user_id: str = Depends(get_current_user_id)):
    try:
        delete_all_documents(user_id)
        return {"message": "Knowledge base cleared."}
    except Exception:
        logger.exception("Failed to clear knowledge base")
        raise HTTPException(status_code=500, detail="Could not clear the knowledge base.")

@app.delete("/delete-document")
def delete_specific_document(
    request: DocumentRequest,
    user_id: str = Depends(get_current_user_id)
):
    try:
        delete_document(request.filename, user_id)
        return {"message": f"Deleted {request.filename}"}
    except Exception:
        logger.exception("Failed to delete %s", request.filename)
        raise HTTPException(status_code=500, detail="Could not delete the document.")

@app.get("/documents")
def get_documents(user_id: str = Depends(get_current_user_id)):
    try:
        return {"documents": list_documents(user_id)}
    except Exception:
        logger.exception("Failed to list documents")
        raise HTTPException(status_code=500, detail="Could not load documents.")

# --- Serve Frontend ---
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def serve_frontend():
    if os.path.exists("app/static/index.html"):
        return FileResponse("app/static/index.html")
    return {"message": "Backend API is running. Please place index.html in /static folder."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
