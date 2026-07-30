"""LLMClient implementations: Ollama (local) and OpenAI.

Sync `complete()` serves the short prompts issued inside prepare() (query
rewriting, expansion) — that path already runs in a worker thread. The async
methods carry the main generation path via httpx.AsyncClient, so a 40-second
answer yields natively instead of pinning an anyio threadpool worker (which
capped whole-API concurrency at ~40 in-flight requests).

Clients are pooled per instance and closed from the app lifespan.
"""
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import openai

from core.config import Settings
from core.exceptions import GenerationError
from core.interfaces import LLMClient

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_api_url
        self._model = settings.llm_model
        # Explicit budget: Ollama's default num_ctx can silently truncate the
        # front of the prompt (the grounding instructions) once retrieved
        # context grows. Low temperature + capped length for grounded QA.
        self._options = {
            "num_ctx": settings.llm_num_ctx,
            "temperature": settings.llm_temperature,
            "num_predict": settings.llm_num_predict,
        }
        # Generous read timeout: CPU inference is slow, but never unbounded.
        self._timeout = httpx.Timeout(
            connect=5.0, read=settings.llm_read_timeout, write=10.0, pool=5.0
        )
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    def _payload(self, prompt: str, stream: bool, system_prompt: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": stream,
            "options": self._options,
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    def _sync(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self._timeout)
        return self._sync_client

    def _async(self) -> httpx.AsyncClient:
        # Created lazily so construction never touches the event loop.
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self._timeout)
        return self._async_client

    def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        try:
            res = self._sync().post(
                f"{self._base_url}generate",
                json=self._payload(prompt, stream=False, system_prompt=system_prompt),
            )
            res.raise_for_status()
        except httpx.HTTPError as e:
            raise GenerationError("Ollama query failed", detail=str(e)) from e
        return str(res.json().get("response", "")).strip()

    async def acomplete(self, prompt: str, system_prompt: str | None = None) -> str:
        try:
            res = await self._async().post(
                f"{self._base_url}generate",
                json=self._payload(prompt, stream=False, system_prompt=system_prompt),
            )
            res.raise_for_status()
        except httpx.HTTPError as e:
            raise GenerationError("Ollama query failed", detail=str(e)) from e
        return str(res.json().get("response", "")).strip()

    async def astream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        try:
            async with self._async().stream(
                "POST",
                f"{self._base_url}generate",
                json=self._payload(prompt, stream=True, system_prompt=system_prompt),
            ) as res:
                res.raise_for_status()
                async for line in res.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue  # one bad frame must not kill the stream
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as e:
            raise GenerationError("Ollama streaming query failed", detail=str(e)) from e

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None


class OpenAIClient(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.openai_api_key
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_num_predict
        self._sync_client: openai.OpenAI | None = None
        self._async_client: openai.AsyncOpenAI | None = None

    @staticmethod
    def _messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _sync(self) -> openai.OpenAI:
        if self._sync_client is None:
            self._sync_client = openai.OpenAI(api_key=self._api_key)
        return self._sync_client

    def _async(self) -> openai.AsyncOpenAI:
        if self._async_client is None:
            self._async_client = openai.AsyncOpenAI(api_key=self._api_key)
        return self._async_client

    def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        try:
            response = self._sync().chat.completions.create(
                model=self._model,
                messages=self._messages(prompt, system_prompt),  # type: ignore[arg-type]
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            raise GenerationError("OpenAI query failed", detail=str(e)) from e

    async def acomplete(self, prompt: str, system_prompt: str | None = None) -> str:
        try:
            response = await self._async().chat.completions.create(
                model=self._model,
                messages=self._messages(prompt, system_prompt),  # type: ignore[arg-type]
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            raise GenerationError("OpenAI query failed", detail=str(e)) from e

    async def astream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        try:
            stream = await self._async().chat.completions.create(
                model=self._model,
                messages=self._messages(prompt, system_prompt),  # type: ignore[arg-type]
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )
            # stream=True always yields AsyncStream at runtime; the SDK's
            # overload widens the static type to a union.
            async for event in cast("openai.AsyncStream[Any]", stream):
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    yield delta
        except Exception as e:
            raise GenerationError("OpenAI streaming query failed", detail=str(e)) from e

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.close()
            self._async_client = None
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.use_openai_llm:
        return OpenAIClient(settings)
    return OllamaClient(settings)


def ollama_model_available(settings: Settings, model: str) -> bool:
    """Startup-time availability probe (non-fatal by design: the ollama
    container may still be pulling models on first boot)."""
    try:
        response = httpx.get(f"{settings.ollama_api_url}tags", timeout=10)
        response.raise_for_status()
        names = [m["name"] for m in response.json().get("models", [])]
        if model not in names:
            logger.error(f"Model '{model}' not found in Ollama. Available: {names}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to check Ollama models: {e}")
        return False
