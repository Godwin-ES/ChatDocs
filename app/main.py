import os
import shutil
import uuid
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi_sso.sso.google import GoogleSSO
from itsdangerous import URLSafeTimedSerializer
from app.agent import get_rag_agent
from app.utils import process_files, delete_document, delete_all_documents, list_document_names
from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, SECRET_KEY, HOST, PORT

app = FastAPI(title="Agentic RAG API")

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

google_sso = GoogleSSO(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    redirect_uri=GOOGLE_REDIRECT_URI,
    allow_insecure_http=True 
)

serializer = URLSafeTimedSerializer(SECRET_KEY)
UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Pydantic Models ---
class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None

class DeleteDocRequest(BaseModel):
    filename: str

# --- Dependencies ---
async def get_current_user_id(request: Request) -> str:
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = serializer.loads(token, max_age=3600*24)
        return data["user_id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

# --- Auth Routes ---
@app.get("/auth/login")
async def login():
    return await google_sso.get_login_redirect()

@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        user = await google_sso.verify_and_process(request)
        session_data = {"email": user.email, "name": user.first_name, "user_id": user.id}
        token = serializer.dumps(session_data)
        response = RedirectResponse(url="/")
        response.set_cookie(key="session_token", value=token, httponly=True, max_age=3600*24)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("session_token")
    return response

@app.get("/auth/me")
async def get_current_user_info(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        data = serializer.loads(token, max_age=3600*24)
        return {"user_id": data["user_id"], "name": data.get("name", "User")}
    except:
        return JSONResponse(status_code=401, content={"detail": "Invalid session"})

# --- RAG Endpoints ---
@app.post("/chat")
async def chat_endpoint(request: ChatRequest, user_id: str = Depends(get_current_user_id)):
    thread_id = request.thread_id or str(uuid.uuid4())
    
    # Initialize Agent
    rag_agent = get_rag_agent(user_id=user_id, session_id=thread_id)
    
    # Generator function to yield chunks
    def stream_generator():
        # Using stream=True explicitly ensures we get a generator back
        response_stream = rag_agent.run(request.message, stream=True)
        for chunk in response_stream:
            # Agno/Phidata chunks usually have a .content attribute
            if hasattr(chunk, "content") and chunk.content:
                yield chunk.content
            elif isinstance(chunk, str):
                yield chunk

    # Return StreamingResponse with Thread ID in headers
    return StreamingResponse(
        stream_generator(), 
        media_type="text/plain",
        headers={"X-Thread-ID": thread_id}
    )

@app.post("/upload")
async def upload_documents(files: List[UploadFile] = File(...), user_id: str = Depends(get_current_user_id)):
    processed_files = []
    for file in files:
        try:
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            process_files(file_path, file.filename, user_id)
            
            if os.path.exists(file_path):
                os.remove(file_path)
            processed_files.append(file.filename)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing {file.filename}: {str(e)}")
    return {"message": "Success", "processed_files": processed_files}

@app.delete("/clear-knowledge")
async def clear_knowledge_base(user_id: str = Depends(get_current_user_id)):
    try:
        delete_all_documents(user_id)
        return {"message": "Knowledge base cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-document")
async def delete_specific_document(
    request: DeleteDocRequest,
    user_id: str = Depends(get_current_user_id)
):
    try:
        delete_document(request.filename, user_id)
        return {"message": f"Deleted {request.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents")
async def list_documents(user_id: str = Depends(get_current_user_id)):
    try:
        files = list_document_names(user_id)
        return {"documents": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Serve Frontend ---
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def serve_frontend():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "Backend API is running. Please place index.html in /static folder."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)