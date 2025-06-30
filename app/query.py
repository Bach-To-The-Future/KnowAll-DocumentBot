from fastapi import APIRouter
from pydantic import BaseModel
from nomic import embed
from app.vectorstore import search_similar
from app.ollama_client import query_ollama
import requests

router = APIRouter()

class QueryRequest(BaseModel):
    question: str

@router.post("/query")
def ask_question(req: QueryRequest):
    q_embed = embed.text([req.question])["embeddings"][0]
    matches = search_similar(q_embed, k=4)

    context = "\n\n".join([m.payload["text"] for m in matches])
    prompt = f"""You are a helpful assistant. Use the context below to answer the question.

Context:
{context}

Question:
{req.question}
"""

    answer = query_ollama(prompt=prompt, model="llama3.2:1b")
    
    return {
        "answer": answer,
        "citations": [m.payload for m in matches]
    }