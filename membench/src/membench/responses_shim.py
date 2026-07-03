"""Local chat-completions -> Responses-API shim.

Some proxied backends (e.g. LiteLLM's `chatgpt/` provider, which fronts a
ChatGPT/Codex session) only work through the Responses API and only in
streaming mode — LiteLLM's own chat->responses bridge returns
"Unknown items in responses API response: []" for them. This shim exposes a
minimal OpenAI chat-completions endpoint locally, forwards to the upstream
`/v1/responses` (streaming), aggregates the SSE stream, and returns a normal
chat-completion JSON — so ChatClient can use those models unchanged.

Usage:
    OPENAI_BASE_URL=http://127.0.0.1:14000/v1 OPENAI_API_KEY=... \
        uv run python -m membench.responses_shim --port 14100
    # then point membench at http://127.0.0.1:14100/v1

Params like temperature/max_tokens are dropped (reasoning backends reject
them); `model` and `messages` pass through.
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx


def aggregate_response_events(lines: list[str]) -> dict:
    """Aggregate an SSE stream into {response, text}.

    The terminal ``response.completed`` event *should* carry the full output,
    but the ChatGPT/Codex backend emits it with an empty ``output`` array —
    the real items only appear in ``response.output_item.done`` events (this
    is the same emptiness that breaks LiteLLM's bridge). So the message text
    is assembled from item-done events, falling back to concatenated
    ``response.output_text.delta`` chunks.
    """
    completed: dict | None = None
    item_texts: list[str] = []
    deltas: list[str] = []
    for line in lines:
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[len("data: ") :])
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind in ("response.completed", "response.incomplete", "response.failed"):
            completed = event
        elif kind == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text" and part.get("text"):
                        item_texts.append(part["text"])
        elif kind == "response.output_text.delta" and event.get("delta"):
            deltas.append(event["delta"])
    if completed is None:
        raise ValueError("no terminal response.* event in SSE stream")
    response = completed.get("response") or {}
    text = "\n".join(item_texts) if item_texts else "".join(deltas)
    if not text:  # last resort: the terminal event's own output items
        for item in response.get("output") or []:
            if item.get("type") == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text" and part.get("text"):
                        text += part["text"]
    return {"response": response, "text": text}


def to_chat_completion(aggregated: dict) -> dict:
    response = aggregated["response"]
    status = response.get("status")
    text = aggregated["text"]
    if not text and status != "completed":
        detail = (response.get("incomplete_details") or {}).get("reason") or status
        raise ValueError(f"upstream response not completed: {detail}")
    usage = response.get("usage") or {}
    return {
        "id": response.get("id", "shim"),
        "object": "chat.completion",
        "model": response.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop" if status == "completed" else "length",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
    }


class ShimHandler(BaseHTTPRequestHandler):
    upstream_base: str = ""
    upstream_key: str = ""
    timeout: float = 300.0

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        if self.path.rstrip("/") not in ("/chat/completions", "/v1/chat/completions"):
            self._reply(404, {"error": {"message": f"unknown path {self.path}"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            payload = {
                "model": request["model"],
                "input": [
                    {"role": m["role"], "content": m["content"]} for m in request["messages"]
                ],
            }
            with (
                httpx.Client(timeout=self.timeout) as client,
                client.stream(
                    "POST",
                    f"{self.upstream_base.rstrip('/')}/responses",
                    headers={"Authorization": f"Bearer {self.upstream_key}"},
                    json=payload,
                ) as upstream,
            ):
                if upstream.status_code >= 400:
                    upstream.read()
                    self._reply(upstream.status_code, {"error": {"message": upstream.text[:500]}})
                    return
                lines = list(upstream.iter_lines())
            aggregated = aggregate_response_events(lines)
            self._reply(200, to_chat_completion(aggregated))
        except Exception as error:  # noqa: BLE001 — surface everything to the client
            self._reply(502, {"error": {"message": f"shim: {error}"}})

    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=14100)
    parser.add_argument("--upstream", default=os.environ.get("OPENAI_BASE_URL", ""))
    args = parser.parse_args()
    if not args.upstream:
        raise SystemExit("set --upstream or OPENAI_BASE_URL")
    ShimHandler.upstream_base = args.upstream
    ShimHandler.upstream_key = os.environ.get("OPENAI_API_KEY", "")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ShimHandler)
    print(f"responses shim on 127.0.0.1:{args.port} -> {args.upstream}/responses")
    server.serve_forever()


if __name__ == "__main__":
    main()
