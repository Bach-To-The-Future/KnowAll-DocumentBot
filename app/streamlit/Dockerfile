FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 -r requirements.txt

# Copy the whole app 
COPY ../../ ./

ENV PYTHONPATH=/app

EXPOSE 8501

CMD ["streamlit", "run", "streamlit/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]