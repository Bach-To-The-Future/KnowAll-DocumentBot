"""Manual smoke check for the Ollama generation path.
Run inside the api container: python tests/test_ollama.py"""
from core.config import get_settings
from integrations.llm_clients import OllamaClient

client = OllamaClient(get_settings())
print(client.complete("What is the capital of France?"))
