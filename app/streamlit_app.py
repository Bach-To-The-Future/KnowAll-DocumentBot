# streamlit_app.py
import streamlit as st
from minio import Minio
import requests
import io
import os
from dotenv import load_dotenv

load_dotenv()

# Load from env or hardcode for now
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Connect to MinIO
client = Minio(
    MINIO_ENDPOINT,
    access_key=ACCESS_KEY,
    secret_key=SECRET_KEY,
    secure=False
)

# Ensure bucket exists
if not client.bucket_exists(BUCKET_NAME):
    client.make_bucket(BUCKET_NAME)

st.title("🧠 Document Chatbot")

uploaded_file = st.file_uploader("Upload a document", type=["csv", "pdf", "txt", "xlsx"])
if uploaded_file:
    object_name = uploaded_file.name
    file_data = uploaded_file.getvalue()
    file_io = io.BytesIO(file_data)

    # Upload to MinIO
    client.put_object(
        BUCKET_NAME,
        object_name,
        file_io,
        length=len(file_data),
        content_type=uploaded_file.type,
    )
    st.success(f"✅ Uploaded {object_name} to MinIO!")

    # Notify FastAPI to process this file from MinIO
    res = requests.post("http://localhost:8000/ingest_from_minio", json={
        "bucket": BUCKET_NAME,
        "object_name": object_name
    })
    if res.ok:
        st.success(res.json())
    else:
        st.error(res.text)

# ✅ List existing files
st.subheader("📂 Files in MinIO:")
res = requests.get("http://localhost:8000/list_documents")
if res.ok:
    for fname in res.json().get("files", []):
        st.markdown(f"- `{fname}`")
else:
    st.error("❌ Failed to fetch files from MinIO")