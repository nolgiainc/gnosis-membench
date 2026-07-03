"""ChatClient behavior against awkward OpenAI-compatible endpoints."""

import json

import httpx

from membench.llm import ChatClient


class RejectTemperatureTransport(httpx.BaseTransport):
    """Mimics reasoning-model endpoints (gpt-5.x) that 400 on `temperature`."""

    def __init__(self):
        self.requests: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        self.requests.append(body)
        if "temperature" in body:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported parameter: 'temperature' is not "
                        "supported with this model.",
                        "code": "invalid_request_body",
                    }
                },
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )


def _client(transport: httpx.BaseTransport) -> ChatClient:
    http = httpx.Client(base_url="http://llm.test", transport=transport)
    return ChatClient("http://llm.test", "test-key", client=http)


def test_complete_drops_rejected_temperature_and_remembers():
    transport = RejectTemperatureTransport()
    client = _client(transport)

    assert client.complete("gpt-5.5", [{"role": "user", "content": "hi"}]) == "ok"
    # first call: with temperature (400), immediate retry without it
    assert "temperature" in transport.requests[0]
    assert "temperature" not in transport.requests[1]

    assert client.complete("gpt-5.5", [{"role": "user", "content": "again"}]) == "ok"
    # subsequent calls skip the rejected param outright (no extra 400)
    assert len(transport.requests) == 3
    assert "temperature" not in transport.requests[2]


def test_complete_keeps_temperature_for_models_that_accept_it():
    class OkTransport(httpx.BaseTransport):
        def __init__(self):
            self.requests = []

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"choices": [{"message": {"content": "fine"}}]})

    transport = OkTransport()
    client = _client(transport)
    assert client.complete("gemma4", [{"role": "user", "content": "hi"}], max_tokens=5) == "fine"
    assert transport.requests[0]["temperature"] == 0.0
    assert transport.requests[0]["max_tokens"] == 5
