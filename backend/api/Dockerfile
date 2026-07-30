# Build context: ./backend (see docker-compose.yml)
FROM python:3.12-slim

WORKDIR /app

# tesseract powers OCR for scanned PDFs (English + French models)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./api/requirements.txt

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 -r api/requirements.txt

# Bake the retrieval models into the image: first boot needs no internet and
# skips the multi-minute cold start. A RERANKER_MODEL env override will still
# download at runtime.
ENV FASTEMBED_CACHE_PATH=/opt/models \
    HF_HOME=/opt/models
RUN python -c "\
from fastembed import SparseTextEmbedding; \
from fastembed.rerank.cross_encoder import TextCrossEncoder; \
SparseTextEmbedding('Qdrant/bm25'); \
TextCrossEncoder('BAAI/bge-reranker-base')" \
    && chown -R 10001 /opt/models && chmod -R a+rX /opt/models

COPY . ./

ENV PYTHONPATH=/app

# Non-root runtime user (uvicorn binds 8000, no privileged ports needed).
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
