import requests
from app.config import Config

config = Config()

OLLAMA_API_URL = "http://localhost:11434/api/generate"

def query_ollama(prompt: str, model: str = config.LLM_MODEL, stream: bool = False, system_prompt: str = None) -> str:
    """
    Send a prompt to the local Ollama server and get the model's response.
    
    Args:
        prompt (str): The user question or input.
        model (str): Model name loaded in Ollama.
        stream (bool): Whether to use streaming output.
        system_prompt (str): Optional system instruction.

    Returns:
        str: The generated response text.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
    }
    
    if system_prompt:
        payload["system"] = system_prompt

    try:
        res = requests.post(OLLAMA_API_URL, json=payload, timeout=120)

        if not res.ok:
            raise Exception(f"Ollama returned {res.status_code}: {res.text}")

        if stream:
            response_text = ""
            for line in res.iter_lines():
                if line:
                    chunk = line.decode("utf-8").strip()
                    response_text += chunk
            return response_text
        else:
            return res.json().get("response", "").strip()

    except Exception as e:
        return f"❌ Error querying Ollama: {e}"
