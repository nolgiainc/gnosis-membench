import json
from pathlib import Path

import httpx
import pytest

from membench import datasets, ingest
from membench.config import Config
from membench.gnosis import GnosisClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def lme_conversations():
    return datasets.load_longmemeval(FIXTURES / "mini_longmemeval.json")


@pytest.fixture
def locomo_conversations():
    return datasets.load_locomo(FIXTURES / "mini_locomo.json")


@pytest.fixture
def cfg(tmp_path):
    return Config(
        gnosis_base_url="http://gnosis.test",
        gnosis_token="test-token",
        tenant_id="nolgia",
        space_id="membench",
        agent_id="membench",
        openai_base_url="http://llm.test/v1",
        openai_api_key="test",
        answer_model="test-answerer",
        judge_model="test-judge",
        max_items=10,
        request_timeout=5.0,
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
    )


class RecordingGnosisTransport(httpx.MockTransport):
    """Mock gnosis API that records every request body per path."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.requests.append((path, body))
        if path == "/v1/memories":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"memory_id": "m1", "content": "stub", "event": "ADD", "metadata": {}}
                    ]
                },
            )
        if path == "/v1/memories/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "memory_id": "m1",
                            "content": "User started learning guitar",
                            "score": 0.9,
                            "metadata": {"session_date": "2023/05/01 (Mon) 10:00"},
                        },
                        {"memory_id": "m2", "content": "User likes pasta", "score": 0.5},
                    ]
                },
            )
        if path == "/v1/memory/context":
            return httpx.Response(
                200,
                json={
                    "sections": [
                        {
                            "source": "long_term",
                            "memory_type": "long_term",
                            "content": "User started learning guitar last month.",
                            "facts": [],
                        }
                    ]
                },
            )
        if path == "/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(404, json={"detail": f"unexpected path {path}"})


@pytest.fixture
def gnosis_transport():
    return RecordingGnosisTransport()


@pytest.fixture
def gnosis_client(gnosis_transport):
    http = httpx.Client(
        base_url="http://gnosis.test",
        headers={"Authorization": "Bearer test-token"},
        transport=gnosis_transport,
    )
    return GnosisClient("http://gnosis.test", "test-token", client=http)


class FakeChat:
    """Callable standing in for ChatClient.complete."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, model, messages, *, temperature=0.0, max_tokens=None):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.responses.pop(0) if self.responses else "yes"

    # answer.py calls .complete(...) on a ChatClient; grade.py takes a bare callable.
    complete = __call__


@pytest.fixture(autouse=True)
def _turn_pair_adds(monkeypatch):
    """Pin the ingest batch to one user/assistant pair per add.

    Production batches 20 turns per add (L-25+); the ingest tests were written
    against pair-sized adds and assert on per-pair replay/retry behavior.
    """
    monkeypatch.setattr(ingest, "TURNS_PER_ADD", 2)
