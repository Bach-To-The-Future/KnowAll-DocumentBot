"""Manual smoke check for the Ollama generation path.

    docker compose exec api python tests/smoke_ollama.py

RENAMED from test_ollama.py. It has no test function, so pytest contributed
zero tests from it -- but pytest IMPORTS a module to collect it, and this
module body makes a real generation call. Measured before the rename:

    $ pytest tests/test_ollama.py --collect-only -q
    The capital of France is Paris.      <- a real LLM call, during --collect-only
    no tests collected in 1.05s

pytest.ini restricts collection to tests/unit, so the default run never hit
it. `pytest tests/`, or any future widening of testpaths, would have -- and in
CI that is a hang or a failure attributed to the wrong thing. The smoke_
prefix takes it out of the discovery pattern entirely rather than relying on
testpaths staying narrow.
"""
from core.config import get_settings
from integrations.llm_clients import OllamaClient

client = OllamaClient(get_settings())
print(client.complete("What is the capital of France?"))
