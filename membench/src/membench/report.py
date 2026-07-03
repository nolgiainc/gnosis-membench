"""Markdown report rendering, formatted like the papers' tables."""

from __future__ import annotations

from typing import Any

from .datasets import LOCOMO, LONGMEMEVAL_CATEGORIES, LONGMEMEVAL_S

LOCOMO_REPORT_CATEGORIES = ("single-hop", "multi-hop", "temporal", "open-domain", "adversarial")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_report(benchmark: str, aggregates: dict[str, dict[str, Any]], run_info: dict) -> str:
    """Render the final markdown report.

    ``aggregates`` maps condition name -> aggregate dict from grade.py.
    """
    lines = [
        f"# gnosis membench report — {benchmark}",
        "",
        f"- answer model: `{run_info.get('answer_model')}`",
        f"- judge model: `{run_info.get('judge_model')}`",
        f"- retrieval depth (max_items/limit): {run_info.get('max_items')}",
        f"- conversations: {run_info.get('conversations')}, questions: {run_info.get('questions')}",
        f"- conditions: {', '.join(aggregates)}",
        "",
    ]
    if benchmark == LONGMEMEVAL_S:
        lines += _render_longmemeval(aggregates)
    elif benchmark == LOCOMO:
        lines += _render_locomo(aggregates)
    else:
        raise ValueError(f"unknown benchmark: {benchmark}")
    lines += [
        "",
        "See README.md for published comparison numbers "
        "(Zep, mem0, A-Mem, full-context baselines).",
        "",
    ]
    return "\n".join(lines)


def _render_longmemeval(aggregates: dict[str, dict[str, Any]]) -> list[str]:
    conditions = list(aggregates)
    header = "| question type | " + " | ".join(conditions) + " | n |"
    sep = "|---" * (len(conditions) + 2) + "|"
    rows = [
        "## Accuracy by question type (LongMemEval paper table format)",
        "",
        header,
        sep,
    ]
    row_keys = [*LONGMEMEVAL_CATEGORIES, "abstention"]
    for key in row_keys:
        cells, n = [], 0
        for condition in conditions:
            stats = aggregates[condition]["categories"].get(key)
            cells.append(_pct(stats["accuracy"]) if stats else "—")
            n = stats["n"] if stats else n
        rows.append(f"| {key} | " + " | ".join(cells) + f" | {n} |")
    for key, label in (
        ("overall_excluding_abstention", "**overall (excl. abstention)**"),
        ("overall", "**overall**"),
    ):
        cells = [_pct(aggregates[c][key]["accuracy"]) for c in conditions]
        n = aggregates[conditions[0]][key]["n"]
        rows.append(f"| {label} | " + " | ".join(cells) + f" | {n} |")
    return rows


def _render_locomo(aggregates: dict[str, dict[str, Any]]) -> list[str]:
    rows = ["## LOCOMO scores by category (F1 / BLEU-1 / J)", ""]
    conditions = list(aggregates)
    header = "| category | " + " | ".join(f"{c} (F1 / B1 / J)" for c in conditions) + " | n |"
    sep = "|---" * (len(conditions) + 2) + "|"
    rows += [header, sep]

    def cell(stats: dict[str, Any] | None) -> str:
        if not stats:
            return "—"
        return f"{stats['f1'] * 100:.1f} / {stats['bleu_1'] * 100:.1f} / {stats['judge'] * 100:.1f}"

    for key in LOCOMO_REPORT_CATEGORIES:
        cells, n = [], 0
        for condition in conditions:
            stats = aggregates[condition]["categories"].get(key)
            cells.append(cell(stats))
            n = stats["n"] if stats else n
        rows.append(f"| {key} | " + " | ".join(cells) + f" | {n} |")
    for key, label in (
        ("overall_excluding_adversarial", "**overall (excl. adversarial)**"),
        ("overall", "**overall**"),
    ):
        cells = [cell(aggregates[c].get(key)) for c in conditions]
        n = aggregates[conditions[0]].get(key, {}).get("n", 0)
        rows.append(f"| {label} | " + " | ".join(cells) + f" | {n} |")
    rows += [
        "",
        "J on adversarial rows uses the official substring rule "
        "(not the LLM judge); the headline J excludes adversarial, matching mem0.",
    ]
    return rows
