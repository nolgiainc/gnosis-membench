"""Stream benchmark conversations into gnosis, turn-pair by turn-pair.

Protocol:
- one gnosis ``user_id`` per benchmark conversation (memory isolation between
  conversations, matching how every published memory system runs these
  benchmarks),
- one gnosis ``session_id`` per benchmark session,
- one extraction-mode add (POST /v1/memories, infer=true) per consecutive
  turn-pair (user + assistant in a single ``messages`` array), so gnosis's
  ingest-time fact extraction (``GNOSIS_FACT_EXTRACTION_ENABLED``) makes one
  LLM call per exchange rather than one per turn,
- session dates (where the benchmark provides them) are carried in the add
  ``metadata`` (``session_date``); gnosis's fact extraction consumes
  ``session_date`` as the conversation date, so extracted units carry absolute
  event dates without mutating benchmark text. ``--inline-dates`` (obsolete
  now that extraction dates units itself) additionally prefixes each turn's
  content with the session date.

Sessions are independent memory streams (ordering only matters within a
session), so ``concurrency`` > 1 ingests sessions in parallel while keeping
each session's adds strictly ordered.

Ingest is resumable: completed conversation ids are recorded in a state file.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import Config
from .datasets import Conversation, Session
from .gnosis import GnosisClient

TURNS_PER_ADD = 2


def user_id_for(conv: Conversation) -> str:
    return f"{conv.benchmark}:{conv.conv_id}"


def session_scope(cfg: Config, conv: Conversation, session_id: str) -> dict[str, str]:
    return GnosisClient.scope(
        tenant_id=cfg.tenant_id,
        space_id=cfg.space_id,
        agent_id=cfg.agent_id,
        session_id=f"{user_id_for(conv)}:{session_id}",
        user_id=user_id_for(conv),
    )


def _ingest_session(
    gnosis: GnosisClient,
    cfg: Config,
    conv: Conversation,
    session: Session,
    *,
    inline_dates: bool,
    log: Callable[[str], None],
) -> int:
    """Ingest one session's turns as ordered turn-pair adds; returns turns written."""
    scope = session_scope(cfg, conv, session.session_id)
    turns = list(session.turns)
    for start in range(0, len(turns), TURNS_PER_ADD):
        pair = turns[start : start + TURNS_PER_ADD]
        messages: list[dict[str, str]] = []
        for turn in pair:
            content = turn.content
            if inline_dates and session.date:
                content = f"[{session.date}] {content}"
            messages.append({"role": turn.role, "content": content})
        metadata: dict[str, Any] = {
            "benchmark": conv.benchmark,
            "conversation_id": conv.conv_id,
            "session_id": session.session_id,
            "turn_index": start,
        }
        if session.date:
            metadata["session_date"] = session.date
        gnosis.add_memory(scope, messages, metadata=metadata)
    log(f"  {conv.conv_id} / {session.session_id}: {len(turns)} turns")
    return len(turns)


def ingest_conversation(
    gnosis: GnosisClient,
    cfg: Config,
    conv: Conversation,
    *,
    inline_dates: bool = False,
    concurrency: int = 1,
    log: Callable[[str], None] = print,
) -> int:
    """Ingest one conversation. Returns the number of turns written."""

    def one(session: Session) -> int:
        return _ingest_session(gnosis, cfg, conv, session, inline_dates=inline_dates, log=log)

    if concurrency <= 1:
        return sum(one(session) for session in conv.sessions)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return sum(pool.map(one, conv.sessions))


def ingest(
    gnosis: GnosisClient,
    cfg: Config,
    conversations: list[Conversation],
    state_path: Path,
    *,
    inline_dates: bool = False,
    concurrency: int = 1,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    state = _load_state(state_path)
    done: set[str] = set(state.get("done", []))
    total_turns = 0
    started = time.time()
    for conv in conversations:
        if conv.conv_id in done:
            log(f"skipping already-ingested conversation {conv.conv_id}")
            continue
        log(f"ingesting conversation {conv.conv_id} ({len(conv.sessions)} sessions)")
        total_turns += ingest_conversation(
            gnosis, cfg, conv, inline_dates=inline_dates, concurrency=concurrency, log=log
        )
        done.add(conv.conv_id)
        state["done"] = sorted(done)
        _save_state(state_path, state)
    return {
        "conversations": len(conversations),
        "turns_written": total_turns,
        "elapsed_s": round(time.time() - started, 1),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
