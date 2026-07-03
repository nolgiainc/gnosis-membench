"""Answer benchmark questions using ONLY memory retrieved from gnosis.

This is the standard memory-benchmark protocol: the answering LLM never sees
the raw conversation history, only what the memory system returns for the
question.

Two retrieval conditions:
- ``context``: POST /v1/memory/context (gnosis's assembled context block)
- ``search``:  POST /v1/memories/search (ranked recall), formatted here with
  each record's ``session_date`` metadata so temporal questions have a chance.

Answer prompts:
- LongMemEval: the official "facts" reading template from the benchmark repo,
  verbatim (src/generation/run_generation.py, retriever_type facts, non-CoT):
  https://github.com/xiaowu0162/LongMemEval/blob/main/src/generation/run_generation.py
- LOCOMO: the official QA_PROMPT / QA_PROMPT_CAT_5 from the benchmark repo,
  verbatim (task_eval/gpt_utils.py), plus the abstention line that the LOCOMO
  authors keep alongside those prompts ("If no information is available ...",
  present in the same file), which the official category-5 scorer depends on:
  https://github.com/snap-research/locomo/blob/main/task_eval/gpt_utils.py
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config
from .datasets import LOCOMO, LONGMEMEVAL_S, Conversation, Question
from .gnosis import GnosisClient
from .ingest import user_id_for
from .llm import ChatClient

CONDITIONS = ("context", "search")

# fmt: off
# --- LongMemEval reading prompt (verbatim; "facts" retriever, non-CoT) ------
LONGMEMEVAL_ANSWER_PROMPT = 'I will give you several facts extracted from history chats between you and a user. Please answer the question based on the relevant facts.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:'

# --- LOCOMO QA prompts (verbatim) -------------------------------------------
LOCOMO_QA_PROMPT = """
Based on the above context, write an answer in the form of a short phrase for the following question. Answer with exact words from the context whenever possible.

Question: {} Short answer:
"""

LOCOMO_QA_PROMPT_CAT_5 = """
Based on the above context, answer the following question.

Question: {} Short answer:
"""

LOCOMO_ABSTENTION_LINE = "If no information is available to answer the question, write 'No information available'."
# fmt: on

LOCOMO_CONTEXT_HEADER = (
    "Below are memories recalled from past conversations between two people: {} and {}.\n\n"
)


def retrieve(
    gnosis: GnosisClient,
    cfg: Config,
    conv: Conversation,
    question: Question,
    condition: str,
) -> str:
    """Retrieve memory for a question under the given condition; return a text block."""
    scope = GnosisClient.scope(
        tenant_id=cfg.tenant_id,
        space_id=cfg.space_id,
        agent_id=cfg.agent_id,
        session_id=f"{user_id_for(conv)}:query",
        user_id=user_id_for(conv),
    )
    if condition == "context":
        sections = gnosis.context(
            scope, question.question, max_items=cfg.max_items, include_graph=cfg.include_graph
        )
        return format_context_sections(sections)
    if condition == "search":
        records = gnosis.search(scope, question.question, limit=cfg.max_items)
        return format_search_results(records)
    raise ValueError(f"unknown condition: {condition}")


def format_context_sections(sections: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for section in sections:
        content = (section.get("content") or "").strip()
        if not content:
            continue
        label = section.get("memory_type") or section.get("source") or "memory"
        blocks.append(f"[{label}]\n{content}")
    return "\n\n".join(blocks) if blocks else "(no memories retrieved)"


def format_search_results(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for record in records:
        content = (record.get("content") or "").strip()
        if not content:
            continue
        metadata = record.get("metadata") or {}
        date = metadata.get("session_date")
        lines.append(f"- ({date}) {content}" if date else f"- {content}")
    return "\n".join(lines) if lines else "(no memories retrieved)"


def build_answer_prompt(conv: Conversation, question: Question, retrieved: str) -> str:
    if conv.benchmark == LONGMEMEVAL_S:
        return LONGMEMEVAL_ANSWER_PROMPT.format(
            retrieved, question.question_date or "unknown", question.question
        )
    if conv.benchmark == LOCOMO:
        header = LOCOMO_CONTEXT_HEADER.format(
            conv.meta.get("speaker_a", "Speaker A"), conv.meta.get("speaker_b", "Speaker B")
        )
        qa_prompt = LOCOMO_QA_PROMPT_CAT_5 if question.category_id == 5 else LOCOMO_QA_PROMPT
        return (
            header
            + retrieved
            + "\n"
            + qa_prompt.format(question.question).rstrip()
            + "\n"
            + LOCOMO_ABSTENTION_LINE
        )
    raise ValueError(f"unknown benchmark: {conv.benchmark}")


def answer_question(
    gnosis: GnosisClient,
    llm: ChatClient,
    cfg: Config,
    conv: Conversation,
    question: Question,
    condition: str,
) -> dict[str, Any]:
    retrieved = retrieve(gnosis, cfg, conv, question, condition)
    prompt = build_answer_prompt(conv, question, retrieved)
    hypothesis = llm.complete(
        cfg.answer_model,
        [{"role": "user", "content": prompt}],
        temperature=0.0,
    ).strip()
    return {
        "benchmark": conv.benchmark,
        "conversation_id": conv.conv_id,
        "question_id": question.question_id,
        "condition": condition,
        "question": question.question,
        "answer": question.answer,
        "category": question.category,
        "category_id": question.category_id,
        "abstention": question.abstention,
        "evidence": list(question.evidence),
        "retrieved": retrieved,
        "hypothesis": hypothesis,
    }


def answer_all(
    gnosis: GnosisClient,
    llm: ChatClient,
    cfg: Config,
    conversations: list[Conversation],
    condition: str,
    out_path: Path,
    *,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Answer every question under one condition, streaming results to JSONL.

    Resumable: question ids already present in ``out_path`` are skipped.
    """
    done: dict[str, dict[str, Any]] = {}
    if out_path.exists():
        with out_path.open() as f:
            for line in f:
                record = json.loads(line)
                done[record["question_id"]] = record
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with out_path.open("a") as out:
        for conv in conversations:
            for question in conv.questions:
                if question.question_id in done:
                    results.append(done[question.question_id])
                    continue
                record = answer_question(gnosis, llm, cfg, conv, question, condition)
                results.append(record)
                out.write(json.dumps(record) + "\n")
                out.flush()
                log(f"  [{condition}] {question.question_id}: {record['hypothesis'][:80]!r}")
    return results
