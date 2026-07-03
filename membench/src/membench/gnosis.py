"""Thin HTTP client for the gnosis memory service.

Endpoints used (see gnosis docs/provider-surface.md):
- POST /v1/memories          extraction-mode add ({scope, messages, infer: true, metadata})
- POST /v1/memories/search   ranked recall ({scope, query, limit})
- POST /v1/memory/context    assembled context block ({scope, query, include_*, max_items})
"""

from __future__ import annotations

from typing import Any

import httpx


class GnosisError(RuntimeError):
    pass


class GnosisClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 300.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    @staticmethod
    def scope(
        *,
        tenant_id: str,
        space_id: str,
        agent_id: str,
        session_id: str,
        user_id: str,
        visibility: str = "private_user",
    ) -> dict[str, str]:
        return {
            "tenant_id": tenant_id,
            "space_id": space_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "user_id": user_id,
            "visibility": visibility,
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=payload)
        if response.status_code >= 400:
            raise GnosisError(f"POST {path} -> {response.status_code}: {response.text[:500]}")
        return response.json()

    def ready(self) -> bool:
        try:
            return self._client.get("/ready").status_code == 200
        except httpx.HTTPError:
            return False

    def add_memory(
        self,
        scope: dict[str, str],
        messages: list[dict[str, str]],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Extraction-mode add: conversation turns become durable memories."""
        payload: dict[str, Any] = {"scope": scope, "messages": messages, "infer": True}
        if metadata:
            payload["metadata"] = metadata
        return self._post("/v1/memories", payload).get("results", [])

    def search(self, scope: dict[str, str], query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        payload = {"scope": scope, "query": query, "limit": limit}
        return self._post("/v1/memories/search", payload).get("results", [])

    def context(
        self,
        scope: dict[str, str],
        query: str,
        *,
        max_items: int = 8,
        include_graph: bool = True,
    ) -> list[dict[str, Any]]:
        payload = {
            "scope": scope,
            "query": query,
            "include_short_term": True,
            "include_long_term": True,
            "include_reasoning": False,
            "include_graph": include_graph,
            "max_items": max_items,
        }
        return self._post("/v1/memory/context", payload).get("sections", [])

    def close(self) -> None:
        self._client.close()
