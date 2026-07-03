"""Minimal OpenAI-compatible chat client (works with OpenAI, LiteLLM, ollama /v1)."""

from __future__ import annotations

import time

import httpx


class ChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 300.0,
        max_retries: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key or 'none'}"},
            timeout=timeout,
        )

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.post("/chat/completions", json=payload)
                if response.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}: {response.text[:200]}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"] or ""
            except (httpx.HTTPError, KeyError) as error:
                last_error = error
                time.sleep(2**attempt)
        raise RuntimeError(f"chat completion failed after retries: {last_error}")

    def close(self) -> None:
        self._client.close()
