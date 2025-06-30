from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from app.ingestion.ingestion_pipeline import process_documents
from app.query import router as query_router
import boto3
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Load from env or hardcode for now
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# FastAPI app
app = FastAPI()
app.include_router(query_router)

s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{MINIO_ENDPOINT}",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
)

# --- OPTIONAL: Keep local upload route for flexibility ---
@app.post("/upload/")
async def upload(file: UploadFile = File(...)):
    os.makedirs("uploaded_docs", exist_ok=True)
    path = os.path.join("uploaded_docs", file.filename)
    
    with open(path, "wb") as f:
        f.write(await file.read())

    try:
        vectors = process_documents(path)
        return {"message": f"{len(vectors)} chunks processed and embedded"}
    except Exception as e:
        return {"error": str(e)}

# --- ✅ New: Ingest from MinIO ---
class MinIOIngestRequest(BaseModel):
    bucket: str
    object_name: str

@app.post("/ingest_from_minio")
async def ingest_from_minio(req: MinIOIngestRequest):
    # Download the file locally
    os.makedirs("minio_downloads", exist_ok=True)
    local_path = os.path.join("minio_downloads", req.object_name)

    try:
        s3.download_file(req.bucket, req.object_name, local_path)
    except Exception as e:
        return {"error": f"Failed to download from MinIO: {str(e)}"}

    try:
        vectors = process_documents(local_path)
        return {"message": f"{len(vectors)} chunks embedded from '{req.object_name}'"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/list_documents")
async def list_documents():
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        objects = [item["Key"] for item in response.get("Contents", [])]
        return {"files": objects}
    except Exception as e:
        logging.error(f"❌ Error listing files in bucket: {e}")
        return {"error": str(e)}
