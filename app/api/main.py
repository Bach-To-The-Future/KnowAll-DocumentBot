import os
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List
from ingestion.ingestion_pipeline import process_documents
from llm.query import router as query_router
from embedding.vectorstore import ensure_collection, delete_vectors_by_source
import boto3, os, logging

from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = Config()

# ENV Configs
MINIO_ENDPOINT = config.MINIO_ENDPOINT
ACCESS_KEY = config.MINIO_ACCESS_KEY
SECRET_KEY = config.MINIO_SECRET_KEY
BUCKET_NAME = config.MINIO_BUCKET

# App
app = FastAPI()
app.include_router(query_router)

# MinIO client
s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{MINIO_ENDPOINT}",
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

def ensure_minio_bucket():
    """Ensure the MinIO bucket exists, create if not."""
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
        logger.info(f"Bucket '{BUCKET_NAME}' exists")
    except s3.exceptions.ClientError as e:
        if e.response['Error']['Code'] == '404':
            logger.info(f"Bucket '{BUCKET_NAME}' does not exist, creating...")
            s3.create_bucket(Bucket=BUCKET_NAME)
        else:
            raise

@app.post("/upload/")
async def upload(file: UploadFile = File(...)):
    try:
        ensure_minio_bucket()
        object_name = file.filename
        s3.upload_fileobj(file.file, BUCKET_NAME, object_name)
        logger.info(f"Uploaded '{object_name}' to MinIO")
    except Exception as e:
        logger.error(f"❌ Failed to upload to MinIO: {e}")
        return {"error": f"❌ Failed to upload to MinIO: {e}"}

    return await ingest_from_minio(MinIOIngestRequest(bucket=BUCKET_NAME, object_name=object_name))

class DeleteDocumentsRequest(BaseModel):
    object_names: List[str]

@app.delete("/delete_documents")
async def delete_documents(payload: DeleteDocumentsRequest):
    deleted = []
    errors = []

    try:
        ensure_minio_bucket()
    except Exception as e:
        logger.error(f"❌ Failed to ensure bucket: {e}")
        return {"error": f"❌ Failed to ensure bucket: {e}"}

    for object_name in payload.object_names:
        try:
            s3.delete_object(Bucket=BUCKET_NAME, Key=object_name)
            delete_vectors_by_source(object_name)
            deleted.append(object_name)
            logger.info(f"🗑️ Deleted '{object_name}' from MinIO and Qdrant.")
        except Exception as e:
            logger.error(f"❌ Failed to delete '{object_name}': {e}")
            errors.append({"file": object_name, "error": str(e)})

    return {
        "deleted": deleted,
        "errors": errors,
        "message": f"🧹 Deleted {len(deleted)} file(s), {len(errors)} error(s)."
    }

class MinIOIngestRequest(BaseModel):
    bucket: str
    object_name: str

@app.post("/ingest_from_minio")
async def ingest_from_minio(req: MinIOIngestRequest):
    os.makedirs("minio_downloads", exist_ok=True)
    local_path = os.path.join("minio_downloads", req.object_name)
    ensure_collection()

    try:
        ensure_minio_bucket()
        s3.download_file(req.bucket, req.object_name, local_path)
        logger.info(f"Downloaded '{req.object_name}' from MinIO to {local_path}")
    except Exception as e:
        logger.error(f"❌ Failed to download from MinIO: {e}")
        return {"error": f"❌ Failed to download from MinIO: {e}"}

    try:
        logger.info(f"🚀 Starting ingestion for: {local_path}")
        vectors = process_documents(local_path)
        if not vectors:
            logger.warning(f"⚠️ No vectors extracted from '{req.object_name}'")
            return {"error": f"⚠️ No vectors extracted from '{req.object_name}'"}

        logger.info(f"🧠 Extracted {len(vectors)} vectors.")
        return {"message": f"✅ {len(vectors)} chunks embedded from '{req.object_name}'"}
    except Exception as e:
        logger.error(f"❌ Failed to process document: {e}")
        return {"error": f"❌ Failed to process document: {e}"}

@app.get("/list_documents")
async def list_documents():
    try:
        ensure_minio_bucket()
        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        contents = response.get("Contents", [])
        if not contents:
            return {"files": []}

        objects = [item["Key"] for item in contents]
        logger.info(f"Listed {len(objects)} files from MinIO")
        return {"files": objects}
    except Exception as e:
        logger.error(f"❌ Error listing files from MinIO: {e}")
        return {"error": "❌ Could not list documents from MinIO."}