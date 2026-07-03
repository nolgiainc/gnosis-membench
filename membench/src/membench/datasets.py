"""Benchmark dataset download, loading, and normalization.

Both benchmarks are normalized into the same shape so ingest/answer/grade
can be benchmark-agnostic where possible:

    Conversation            one benchmark unit sharing a memory store
      .sessions[]           chat sessions, each with an (optional) date
        .turns[]            {role, content}
      .questions[]          questions asked against that memory store

Format sources:
- LongMemEval (https://github.com/xiaowu0162/LongMemEval): a JSON list of
  500 question instances; each instance carries its own haystack of chat
  sessions (``haystack_sessions`` + parallel ``haystack_dates`` /
  ``haystack_session_ids``). One instance == one Conversation here, keyed
  by ``question_id``, with exactly one Question. Abstention instances are
  marked by the ``_abs`` suffix on ``question_id``.
- LOCOMO (https://github.com/snap-research/locomo): ``data/locomo10.json``,
  a JSON list of 10 samples; each has a two-speaker ``conversation`` with
  ``session_<n>`` turn lists and ``session_<n>_date_time`` timestamps, and
  a ``qa`` list with categories 1-5 (multi-hop, temporal, open-domain,
  single-hop, adversarial). One sample == one Conversation with many
  Questions. Adversarial questions carry ``adversarial_answer``.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LONGMEMEVAL_S = "longmemeval_s"
LOCOMO = "locomo"
BENCHMARKS = (LONGMEMEVAL_S, LOCOMO)

DOWNLOADS: dict[str, tuple[str, str]] = {
    # benchmark -> (filename, url)
    LONGMEMEVAL_S: (
        "longmemeval_s_cleaned.json",
        "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json",
    ),
    LOCOMO: (
        "locomo10.json",
        "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
    ),
}

LOCOMO_CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}

# The order LongMemEval's paper reports categories in (Table 3-style rows).
LONGMEMEVAL_CATEGORIES = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "knowledge-update",
    "temporal-reasoning",
)


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Session:
    session_id: str
    date: str | None
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class Question:
    question_id: str
    question: str
    answer: str
    category: str  # LongMemEval question_type, or LOCOMO category name
    category_id: int | None = None  # LOCOMO numeric category (1-5)
    question_date: str | None = None
    abstention: bool = False
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Conversation:
    benchmark: str
    conv_id: str
    sessions: tuple[Session, ...]
    questions: tuple[Question, ...]
    meta: dict = field(default_factory=dict)


def dataset_path(benchmark: str, data_dir: Path) -> Path:
    filename, _ = DOWNLOADS[benchmark]
    return data_dir / filename


def download(benchmark: str, data_dir: Path, *, force: bool = False) -> Path:
    """Download a benchmark data file if not already present."""
    filename, url = DOWNLOADS[benchmark]
    target = data_dir / filename
    if target.exists() and not force:
        return target
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URLs
    tmp.rename(target)
    return target


def load(benchmark: str, path: Path, *, subset: int | None = None) -> list[Conversation]:
    if benchmark == LONGMEMEVAL_S:
        return load_longmemeval(path, subset=subset)
    if benchmark == LOCOMO:
        return load_locomo(path, subset=subset)
    raise ValueError(f"unknown benchmark: {benchmark}")


# --------------------------------------------------------------------------
# LongMemEval
# --------------------------------------------------------------------------


def load_longmemeval(path: Path, *, subset: int | None = None) -> list[Conversation]:
    entries = json.loads(Path(path).read_text())
    if subset is not None:
        entries = entries[:subset]
    conversations: list[Conversation] = []
    for entry in entries:
        qid = str(entry["question_id"])
        raw_sessions = entry["haystack_sessions"]
        dates = entry.get("haystack_dates") or [None] * len(raw_sessions)
        session_ids = entry.get("haystack_session_ids") or [
            f"session_{i}" for i in range(len(raw_sessions))
        ]
        sessions = []
        for sid, date, turns in zip(session_ids, dates, raw_sessions, strict=True):
            parsed = tuple(
                Turn(role=t["role"], content=t["content"])
                for t in turns
                if t.get("role") in ("user", "assistant") and (t.get("content") or "").strip()
            )
            if parsed:
                sessions.append(Session(session_id=str(sid), date=date, turns=parsed))
        question = Question(
            question_id=qid,
            question=str(entry["question"]),
            answer=str(entry["answer"]),
            category=str(entry["question_type"]),
            question_date=entry.get("question_date"),
            abstention="_abs" in qid,
        )
        conversations.append(
            Conversation(
                benchmark=LONGMEMEVAL_S,
                conv_id=qid,
                sessions=tuple(sessions),
                questions=(question,),
                meta={"answer_session_ids": entry.get("answer_session_ids", [])},
            )
        )
    return conversations


# --------------------------------------------------------------------------
# LOCOMO
# --------------------------------------------------------------------------

_SESSION_KEY = re.compile(r"^session_(\d+)$")


def load_locomo(path: Path, *, subset: int | None = None) -> list[Conversation]:
    samples = json.loads(Path(path).read_text())
    if subset is not None:
        samples = samples[:subset]
    conversations: list[Conversation] = []
    for sample in samples:
        conv = sample["conversation"]
        speaker_a = conv.get("speaker_a", "Speaker A")
        speaker_b = conv.get("speaker_b", "Speaker B")
        session_nums = sorted(
            int(m.group(1))
            for key in conv
            if (m := _SESSION_KEY.match(key)) and isinstance(conv[key], list)
        )
        sessions = []
        for num in session_nums:
            date = conv.get(f"session_{num}_date_time")
            turns = []
            for t in conv[f"session_{num}"]:
                speaker = t.get("speaker", "")
                text = (t.get("text") or "").strip()
                caption = (t.get("blip_caption") or "").strip()
                if caption:
                    text = f"{text} [shared a photo: {caption}]".strip()
                if not text:
                    continue
                role = "user" if speaker == speaker_a else "assistant"
                turns.append(Turn(role=role, content=f"{speaker}: {text}"))
            if turns:
                sessions.append(Session(session_id=f"session_{num}", date=date, turns=tuple(turns)))
        conv_id = str(sample.get("sample_id", f"sample_{len(conversations)}"))
        questions = []
        for i, qa in enumerate(sample.get("qa", [])):
            category_id = int(qa["category"])
            answer = qa.get("answer")
            if answer is None:
                answer = qa.get("adversarial_answer", "No information available")
            evidence = qa.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]
            questions.append(
                Question(
                    question_id=f"{conv_id}:qa_{i}",
                    question=str(qa["question"]),
                    answer=str(answer),
                    category=LOCOMO_CATEGORY_NAMES.get(category_id, str(category_id)),
                    category_id=category_id,
                    abstention=category_id == 5,
                    evidence=tuple(str(e) for e in evidence),
                )
            )
        conversations.append(
            Conversation(
                benchmark=LOCOMO,
                conv_id=conv_id,
                sessions=tuple(sessions),
                questions=tuple(questions),
                meta={"speaker_a": speaker_a, "speaker_b": speaker_b},
            )
        )
    return conversations
