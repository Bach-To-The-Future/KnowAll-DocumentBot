import requests
import json
from config import Config
import openai
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = Config()

OLLAMA_API_URL = config.OLLAMA_API_URL
LLM_MODEL = config.LLM_MODEL
USE_OPENAI_LLM = config.USE_OPENAI_LLM

def query_ollama(prompt: str, model: str = LLM_MODEL, stream: bool = False, system_prompt: str = None) -> str:
    """Send a prompt to the local Ollama server and get the model's response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
    }
    
    if system_prompt:
        payload["system"] = system_prompt

    try:
        res = requests.post(f"{OLLAMA_API_URL}generate", json=payload, timeout=120)
        res.raise_for_status()

        if stream:
            response_text = ""
            for line in res.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    response_text += chunk.get("response", "")
            return response_text
        else:
            return res.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"Ollama query failed: {e}")
        return f"❌ Error querying Ollama: {e}"

def query_openai(prompt: str, model: str = LLM_MODEL, system_prompt: str = None) -> str:
    """Send a prompt to OpenAI API and get the model's response."""
    try:
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI query failed: {e}")
        return f"❌ Error querying OpenAI: {e}"

def query_llm(prompt: str, model: str = LLM_MODEL, stream: bool = False, system_prompt: str = None) -> str:
    """Route query to either Ollama or OpenAI based on configuration."""
    if USE_OPENAI_LLM:
        return query_openai(prompt, model, system_prompt)
    return query_ollama(prompt, model, stream, system_prompt)

if __name__ == "__main__":
    prompt = "Explain how transformers work in AI."
    response = query_llm(prompt)
    print("Response:\n", response)