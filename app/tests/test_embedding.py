import requests

resp = requests.post(
    "http://ollama:11434/api/embeddings",
    json={"model": "nomic-embed-text", "prompt": "hello world"},
    timeout=60
)
print(resp.status_code)
print(resp.text)