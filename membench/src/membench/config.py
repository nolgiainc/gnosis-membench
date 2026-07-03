"""Runtime configuration, sourced from environment variables.

All LLM traffic (answer generation and LLM-judge grading) goes through a
single OpenAI-compatible endpoint configured with OPENAI_BASE_URL /
OPENAI_API_KEY. gnosis itself is configured separately (see stack/compose.yaml).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Config:
    # gnosis service
    gnosis_base_url: str = field(
        default_factory=lambda: _env("GNOSIS_BASE_URL", "http://localhost:8080")
    )
    gnosis_token: str = field(default_factory=lambda: _env("GNOSIS_TOKEN", "membench-token"))
    tenant_id: str = field(default_factory=lambda: _env("MEMBENCH_TENANT_ID", "bromigos"))
    space_id: str = field(default_factory=lambda: _env("MEMBENCH_SPACE_ID", "membench"))
    agent_id: str = field(default_factory=lambda: _env("MEMBENCH_AGENT_ID", "membench"))

    # OpenAI-compatible endpoint for answerer + judge
    openai_base_url: str = field(
        default_factory=lambda: _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    answer_model: str = field(default_factory=lambda: _env("MEMBENCH_ANSWER_MODEL", "gpt-4o-mini"))
    judge_model: str = field(default_factory=lambda: _env("MEMBENCH_JUDGE_MODEL", "gpt-4o"))

    # retrieval depth for both conditions
    max_items: int = field(default_factory=lambda: int(_env("MEMBENCH_MAX_ITEMS", "20")))

    # include_graph for /v1/memory/context. gnosis's graph-QA planner passes
    # GNOSIS_LLM verbatim to a raw OpenAI client, so LiteLLM-style model names
    # ("openai/...") 500 the endpoint unless gnosis actually sits behind a
    # LiteLLM proxy. Set MEMBENCH_INCLUDE_GRAPH=false when gnosis points at a
    # bare OpenAI-compatible endpoint such as ollama /v1.
    include_graph: bool = field(
        default_factory=lambda: _env("MEMBENCH_INCLUDE_GRAPH", "true").lower() == "true"
    )

    request_timeout: float = field(default_factory=lambda: float(_env("MEMBENCH_TIMEOUT", "300")))

    data_dir: Path = field(
        default_factory=lambda: Path(_env("MEMBENCH_DATA_DIR", str(_REPO_ROOT / "data")))
    )
    results_dir: Path = field(
        default_factory=lambda: Path(_env("MEMBENCH_RESULTS_DIR", str(_REPO_ROOT / "results")))
    )


def load_config() -> Config:
    return Config()
