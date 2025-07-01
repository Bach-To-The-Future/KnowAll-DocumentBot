from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from nomic import embed
from app.vectorstore import search_similar
from app.ollama_client import query_ollama
from app.config import Config

config = Config()
router = APIRouter()


# --- ✅ Request Schema ---
class QueryRequest(BaseModel):
    question: str
    documents: list[str] | None = None  # Optional filter by filenames


# --- ✅ Response Schema (optional, for stricter typing) ---
class Citation(BaseModel):
    index: int
    text: str
    source: str
    page_number: str | int


# --- ✅ Query Endpoint ---
@router.post("/query")
def ask_question(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question field is required.")

    # --- Step 1: Embed question ---
    try:
        q_embed = embed.text([req.question], model=config.EMBED_MODEL)["embeddings"][0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    # --- Step 2: Search in vector DB ---
    try:
        matches = search_similar(q_embed, k=4)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {e}")

    if not matches:
        return {
            "answer_with_refs": "❌ No relevant documents found.",
            "citations": []
        }

    # --- Step 3: Prepare context with citations ---
    citations = []
    numbered_context = ""
    for idx, match in enumerate(matches, 1):
        payload = match.payload or {}

        text = payload.get("text", "")
        source = payload.get("source", "unknown")
        page = payload.get("page_number", "?")

        citations.append({
            "index": idx,
            "text": text,
            "source": source,
            "page_number": page
        })

        numbered_context += f"[{idx}] {text}\n\n"

    # --- Step 4: Construct prompt for LLM ---
    prompt = f"""You are a knowledgeable document chatbot. Use only the numbered context documents below to answer the user's question as accurately and concisely as possible. 
    If you reference specific information, cite the relevant reference number(s) in square brackets, like [1], [2], etc. 
    If the information is not available in the context, politely say so.

    Context:
    {numbered_context}

    Question:
    {req.question}
    """

    # --- Step 5: Query LLM ---
    try:
        answer = query_ollama(prompt=prompt, model="llama3.2:1b")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM query failed: {e}")

    return {
        "answer_with_refs": answer.strip(),
        "citations": citations
    }
