from fastapi import FastAPI, UploadFile, File
from app.ingestion.ingestion_pipeline import process_documents
import os

app = FastAPI()

@app.post("/Upload/")
async def upload(file: UploadFile = File(...)):
    path = f"./uploaded_docs/{file.filename}"
    with open(path, "wb") as f:
        f.write(await file.read())

    try:
        vectors = process_documents(path)
        return {"message": f"{len(vectors)} chunks processed and embedded"}
    except Exception as e:
        return {"error": str(e)}
     