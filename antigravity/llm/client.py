"""
Ollama HTTP client — Async streaming chat via OpenAI-compatible /v1 API.

Uses httpx for streaming SSE responses from the Ollama server.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from antigravity.config import Config


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OllamaClient:
    """
    Async HTTP client for Ollama's OpenAI-compatible /v1/chat/completions endpoint.

    Supports streaming token-by-token response via Server-Sent Events (SSE).
    """

    def __init__(self, config: Config):
        self.base_url = config.ollama.host.rstrip("/")
        self.model = config.ollama.model
        self.temperature = config.ollama.temperature
        self.context_size = config.ollama.context_size
        self.timeout = config.ollama.timeout

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """
        Stream a chat completion request, yielding text tokens as they arrive.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.

        Yields:
            String tokens from the model response.

        Raises:
            ConnectionError: If the Ollama server is unreachable.
            httpx.HTTPStatusError: If the server returns an error status.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
            "options": {
                "num_ctx": self.context_size,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"]
                            content = delta.get("content") or ""
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Cannot reach Ollama server at {self.base_url}.\n"
                f"Make sure the server is running and accessible.\n"
                f"Detail: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Ollama request timed out after {self.timeout}s.\n"
                f"The model may be loading or the server is overloaded."
            ) from e

    async def health_check(self) -> dict:
        """
        Check if the Ollama server is reachable and return server info.

        Returns:
            Dict with 'ok' bool and optional 'error' message.
        """
        # Try the base Ollama endpoint (not /v1)
        base = self.base_url.replace("/v1", "").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {"ok": True, "models": models}
                return {"ok": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def list_models(self) -> list[str]:
        """Return list of available model names from the Ollama server."""
        result = await self.health_check()
        return result.get("models", [])
