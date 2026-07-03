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
        # Params (per model) that the endpoint has rejected as unsupported.
        # Reasoning-model families (e.g. gpt-5.x) hard-reject `temperature`;
        # we drop the offending param and remember, so every subsequent call
        # skips it instead of burning a 400 + retry each time.
        self._unsupported_params: dict[str, set[str]] = {}
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key or 'none'}"},
            timeout=timeout,
        )

    # Param -> markers identifying it in an endpoint rejection body. Note:
    # `max_tokens` can be rejected under its responses-API name
    # (`max_output_tokens`) when a proxy translates chat -> responses, and
    # such rejections may surface as a 4xx or a proxy-wrapped 5xx.
    _DROPPABLE_PARAMS: dict[str, tuple[str, ...]] = {
        "temperature": ("'temperature'",),
        "max_tokens": ("'max_tokens'", "max_output_tokens"),
    }
    _REJECTION_MARKERS = ("unsupported parameter", "unable to complete request")

    def _rejected_param_in(self, body: str, payload: dict) -> str | None:
        lowered = body.lower()
        if not any(marker in lowered for marker in self._REJECTION_MARKERS):
            return None
        for param, markers in self._DROPPABLE_PARAMS.items():
            if param in payload and any(marker in lowered for marker in markers):
                return param
        return None

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
        for param in self._unsupported_params.get(model, ()):
            payload.pop(param, None)
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.post("/chat/completions", json=payload)
                if response.status_code >= 400:
                    param = self._rejected_param_in(response.text, payload)
                    if param is not None:
                        self._unsupported_params.setdefault(model, set()).add(param)
                        payload.pop(param)
                        continue  # immediate retry without the rejected param
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
