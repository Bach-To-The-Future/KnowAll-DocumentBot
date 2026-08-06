# Build context: ./backend (see docker-compose.yml)
#
# Base image pinned BY DIGEST, not by tag (finding #25). `python:3.12-slim` is
# republished on every security refresh, so a tag-only build is not
# reproducible and an eval baseline recorded against one build cannot be
# compared to another. The tag is kept in the comment for readability.
#   python:3.12-slim as of 2026-07-14
FROM python@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461

WORKDIR /app

# tesseract powers OCR for scanned PDFs (English + French).
#
# Finding #26, now CLOSED. The base-image digest pins the tesseract BINARY; it
# does NOT pin the traineddata. `tesseract-ocr-fra` resolved against Debian's
# archive at build time, so a traineddata refresh would change OCR output with
# no diff anywhere in this repository — and OCR output is corpus content, so
# every stored vector and every eval number would move silently.
#
# Engine from apt; language data vendored and checksummed below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Language data pinned by checksum rather than by archive state.
# tesseract-ocr/tessdata @ 4.1.0 — the standard models Debian also ships, chosen
# so vendoring PINS current behaviour instead of changing it.
#
# The per-language apt packages are deliberately NOT installed, so there is no
# system copy for TESSDATA_PREFIX to be shadowed by. A vendored file sitting
# unused beside a system copy is exactly the failure this prevents, which is
# why scripts/verify_ocr.py asserts RESOLUTION rather than presence.
COPY vendor/tessdata/ /opt/tessdata/
ENV TESSDATA_PREFIX=/opt/tessdata
# In a real script file rather than an inline `python -c`: an embedded
# multi-line command already broke this Dockerfile once (finding #25), and the
# same pattern is used by api/verify_model_pins.py.
COPY api/verify_tessdata.py /tmp/verify_tessdata.py
RUN python /tmp/verify_tessdata.py && rm /tmp/verify_tessdata.py

COPY api/requirements.txt ./api/requirements.txt

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 -r api/requirements.txt

# Bake the retrieval models into the image: first boot needs no internet and
# skips the multi-minute cold start.
#
# Model revisions are pinned and then VERIFIED (finding #25):
#   1. snapshot_download() fetches the exact commits into the HF cache.
#   2. the fastembed constructors run (they populate the cache themselves).
#   3. verify_model_pins.py asserts the pinned commits are the ones cached,
#      failing the BUILD if fastembed resolved a newer default branch.
# HF_HUB_OFFLINE=1 was tried as the enforcement mechanism and does NOT work:
# fastembed does not resolve through the plain huggingface_hub cache layout and
# fails with "Could not load model Qdrant/bm25 from any source".
ENV FASTEMBED_CACHE_PATH=/opt/models \
    HF_HOME=/opt/models
ARG BM25_REVISION=e499a1f8d6bec960aab5533a0941bf914e70faf9
ARG RERANKER_REVISION=2cfc18c9415c912f9d8155881c133215df768a70
COPY api/verify_model_pins.py /tmp/verify_model_pins.py
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('Qdrant/bm25', revision='${BM25_REVISION}'); snapshot_download('BAAI/bge-reranker-base', revision='${RERANKER_REVISION}')" \
    && python -c "from fastembed import SparseTextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; SparseTextEmbedding('Qdrant/bm25'); TextCrossEncoder('BAAI/bge-reranker-base')" \
    && python /tmp/verify_model_pins.py "${BM25_REVISION}" "${RERANKER_REVISION}" \
    && rm /tmp/verify_model_pins.py \
    && chown -R 10001 /opt/models && chmod -R a+rX /opt/models

# Recorded in the image so a running container can report exactly which model
# revisions it holds — this feeds the baseline provenance tuple.
# Env names deliberately differ from the ARG names: Docker resolves a
# self-referencing `ENV FOO=${FOO}` against a same-named ARG to the EMPTY
# string, which silently recorded "unpinned" provenance on the first attempt.
ENV KNOWALL_BM25_REVISION=${BM25_REVISION} \
    KNOWALL_RERANKER_REVISION=${RERANKER_REVISION}

COPY . ./

ENV PYTHONPATH=/app

# Non-root runtime user (uvicorn binds 8000, no privileged ports needed).
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
