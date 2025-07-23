FROM python:3.12-slim

WORKDIR /app

COPY app/streamlit_ui/requirements.txt ./streamlit_ui/requirements.txt

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 -r streamlit_ui/requirements.txt

COPY app/ ./

ENV PYTHONPATH=/app

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_ui/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]