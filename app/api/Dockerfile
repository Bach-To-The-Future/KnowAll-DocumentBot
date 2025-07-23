FROM python:3.12-slim

WORKDIR /app

COPY app/api/requirements.txt ./api/requirements.txt

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 -r api/requirements.txt

COPY app/ ./

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]