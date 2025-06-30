from app.ollama_client import query_ollama

response = query_ollama("What is the capital of France?")
print(response)