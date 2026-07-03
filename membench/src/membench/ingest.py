"""Stream benchmark conversations into gnosis, turn by turn.

Protocol:
- one gnosis ``user_id`` per benchmark conversation (memory isolation between
  conversations, matching how every published memory system runs these
  benchmarks),
- one gnosis ``session_id`` per benchmark session,
- one extraction-mode add (POST /v1/memories, infer=true) per turn,
- session dates (where the benchmark provides them) are carried in the add
  ``metadata`` (``session_date``); gnosis has no ingest-time timestamp
  override, so ``created_at`` on the stored memory reflects ingest time, not
  the haystack date. ``--inline-dates`` additionally prefixes each turn's
  content with the session date so extraction can pick dates up into memory
  content (helps temporal-reasoning questions; disabled by default because it
  mutates the benchmark text).

Ingest is resumable: completed conversation ids are recorded in a state file.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config
from .datasets import Conversation
from .gnosis import GnosisClient


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


def ingest_conversation(
    gnosis: GnosisClient,
    cfg: Config,
    conv: Conversation,
    *,
    inline_dates: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    """Ingest one conversation. Returns the number of turns written."""
    written = 0
    for session in conv.sessions:
        scope = session_scope(cfg, conv, session.session_id)
        for turn_index, turn in enumerate(session.turns):
            content = turn.content
            if inline_dates and session.date:
                content = f"[{session.date}] {content}"
            metadata: dict[str, Any] = {
                "benchmark": conv.benchmark,
                "conversation_id": conv.conv_id,
                "session_id": session.session_id,
                "turn_index": turn_index,
            }
            if session.date:
                metadata["session_date"] = session.date
            gnosis.add_memory(
                scope,
                [{"role": turn.role, "content": content}],
                metadata=metadata,
            )
            written += 1
        log(f"  {conv.conv_id} / {session.session_id}: {len(session.turns)} turns")
    return written


def ingest(
    gnosis: GnosisClient,
    cfg: Config,
    conversations: list[Conversation],
    state_path: Path,
    *,
    inline_dates: bool = False,
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
        total_turns += ingest_conversation(gnosis, cfg, conv, inline_dates=inline_dates, log=log)
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
