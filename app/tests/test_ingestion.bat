@echo off
curl -X POST http://localhost:8000/ingest_from_minio ^
     -H "Content-Type: application/json" ^
     -d "{\"bucket\": \"knowall\", \"object_name\": \"Data Engineer Concepts.docx\"}"
pause
