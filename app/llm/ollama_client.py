import requests
import json
from config import Config

config = Config()

OLLAMA_API_URL = config.OLLAMA_API_URL
LLM_MODEL = config.LLM_MODEL

def query_ollama(prompt: str, model: str = LLM_MODEL, stream: bool = False, system_prompt: str = None) -> str:
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
        res = requests.post(f"{OLLAMA_API_URL}generate", json=payload, timeout=120)

        if not res.ok:
            raise Exception(f"Ollama returned {res.status_code}: {res.text}")

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
        return f"❌ Error querying Ollama: {e}"

if __name__ == "__main__":
    prompt = "Explain how transformers work in AI."
    response = query_ollama(prompt)
    print("Response:\n", response)