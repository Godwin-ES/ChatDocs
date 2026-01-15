from dotenv import load_dotenv, find_dotenv
from agno.agent import Agent
from agno.db.mongo import MongoDb
from agno.models.openai import OpenAIChat
from app.utils import get_knowledge_base
from app.prompts import rag_prompt
from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL, MONGO_DB_NAME, MONGO_URL

memory_db = MongoDb(db_name=MONGO_DB_NAME, db_url=MONGO_URL)
model = OpenAIChat(id=GROQ_MODEL, api_key=GROQ_API_KEY, base_url=GROQ_URL)

def get_rag_agent(user_id, session_id):
    knowledge = get_knowledge_base(user_id)
    rag_agent = Agent(model=model,
                      name="RAGAgent",
                      instructions=rag_prompt,
                      db=memory_db,
                      session_id=session_id,
                      user_id=user_id,
                      enable_agentic_memory=True, 
                      enable_session_summaries=True, 
                      knowledge=knowledge,
                      search_knowledge=True,
                      stream=True
                )
    return rag_agent