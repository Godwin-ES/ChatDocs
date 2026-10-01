from agno.agent import Agent
from agno.db.mongo import MongoDb
from agno.models.openai import OpenAIChat
from app.utils import get_knowledge_base, list_documents
from app.prompts import build_rag_prompt
from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL, MONGO_DB_NAME, MONGO_URL

memory_db = MongoDb(db_name=MONGO_DB_NAME, db_url=MONGO_URL)
model = OpenAIChat(id=GROQ_MODEL, api_key=GROQ_API_KEY, base_url=GROQ_URL)

def get_rag_agent(user_id, session_id, user_name=None):
    knowledge = get_knowledge_base(user_id)
    docs = list_documents(user_id)
    ready = [d["filename"] for d in docs if d["status"] == "ready"]
    processing = [d["filename"] for d in docs if d["status"] == "processing"]
    rag_agent = Agent(model=model,
                      name="RAGAgent",
                      instructions=build_rag_prompt(ready, user_name, processing),
                      db=memory_db,
                      session_id=session_id,
                      user_id=user_id,
                      # Recent turns give the model conversational context for follow-ups.
                      # This replaces session summaries, which cost an extra LLM call per turn.
                      add_history_to_context=True,
                      num_history_runs=6,
                      enable_agentic_memory=True,
                      knowledge=knowledge,
                      search_knowledge=True,
                      references_format="json",
                      markdown=True,
                      add_datetime_to_context=True,
                      stream=True
                )
    return rag_agent
