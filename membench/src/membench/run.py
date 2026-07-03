"""CLI orchestrator: download / ingest -> answer -> grade -> report.

Usage:
    membench download --benchmark longmemeval_s
    membench run --benchmark locomo --subset 2 --conditions context,search
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import answer as answer_mod
from . import datasets, grade, ingest, report
from .config import load_config
from .gnosis import GnosisClient
from .llm import ChatClient

STAGES = ("ingest", "answer", "grade")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="membench")
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="download benchmark data files")
    dl.add_argument("--benchmark", choices=datasets.BENCHMARKS, required=True)
    dl.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="run ingest -> answer -> grade -> report")
    run.add_argument("--benchmark", choices=datasets.BENCHMARKS, required=True)
    run.add_argument("--subset", type=int, default=None, help="only the first N conversations")
    run.add_argument(
        "--conditions",
        default="context,search",
        help="comma-separated retrieval conditions: context,search",
    )
    run.add_argument(
        "--stages",
        default=",".join(STAGES),
        help="comma-separated stages to run (default: ingest,answer,grade)",
    )
    run.add_argument("--data-file", type=Path, default=None, help="override benchmark data file")
    run.add_argument("--out", type=Path, default=None, help="output directory for this run")
    run.add_argument(
        "--inline-dates",
        action="store_true",
        help="also prefix ingested turn content with the session date (see ingest.py)",
    )

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.command == "download":
        path = datasets.download(args.benchmark, cfg.data_dir, force=args.force)
        print(f"downloaded {args.benchmark} -> {path}")
        return 0

    return _run(args, cfg)


def _run(args: argparse.Namespace, cfg) -> int:
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    for condition in conditions:
        if condition not in answer_mod.CONDITIONS:
            print(f"error: unknown condition {condition!r}", file=sys.stderr)
            return 2
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    for stage in stages:
        if stage not in STAGES:
            print(f"error: unknown stage {stage!r}", file=sys.stderr)
            return 2

    data_file = args.data_file or datasets.dataset_path(args.benchmark, cfg.data_dir)
    if not data_file.exists():
        print(
            f"error: {data_file} not found. Run: membench download --benchmark {args.benchmark}",
            file=sys.stderr,
        )
        return 2
    conversations = datasets.load(args.benchmark, data_file, subset=args.subset)
    n_questions = sum(len(c.questions) for c in conversations)
    print(f"loaded {len(conversations)} conversations / {n_questions} questions from {data_file}")

    out_dir = args.out or (
        cfg.results_dir / args.benchmark / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"writing results to {out_dir}")

    gnosis = GnosisClient(cfg.gnosis_base_url, cfg.gnosis_token, timeout=cfg.request_timeout)
    llm = ChatClient(cfg.openai_base_url, cfg.openai_api_key, timeout=cfg.request_timeout)

    if "ingest" in stages:
        if not gnosis.ready():
            print(f"error: gnosis not ready at {cfg.gnosis_base_url}", file=sys.stderr)
            return 1
        state_path = out_dir / "ingest_state.json"
        summary = ingest.ingest(
            gnosis, cfg, conversations, state_path, inline_dates=args.inline_dates
        )
        print(f"ingest complete: {summary}")

    answers: dict[str, list[dict]] = {}
    if "answer" in stages:
        for condition in conditions:
            print(f"answering under condition: {condition}")
            answers[condition] = answer_mod.answer_all(
                gnosis, llm, cfg, conversations, condition, out_dir / f"answers_{condition}.jsonl"
            )

    if "grade" in stages:
        aggregates: dict[str, dict] = {}
        for condition in conditions:
            records = answers.get(condition) or _read_jsonl(out_dir / f"answers_{condition}.jsonl")
            if not records:
                print(f"error: no answers for condition {condition!r}", file=sys.stderr)
                return 1
            # Resumable: previously graded records (streamed to the jsonl as
            # they were scored) are kept; only the remainder hits the judge.
            graded_path = out_dir / f"graded_{condition}.jsonl"
            already = {r["question_id"]: r for r in _read_jsonl(graded_path)}
            pending = [r for r in records if r["question_id"] not in already]
            print(
                f"grading condition: {condition} "
                f"({len(records)} answers, {len(already)} already graded)"
            )
            grade_fn = (
                grade.grade_longmemeval
                if args.benchmark == datasets.LONGMEMEVAL_S
                else grade.grade_locomo
            )
            with graded_path.open("a") as graded_out:

                def stream(record: dict, out=graded_out) -> None:
                    out.write(json.dumps(record) + "\n")
                    out.flush()

                newly = grade_fn(llm.complete, cfg.judge_model, pending, on_record=stream)
            by_id = {**already, **{r["question_id"]: r for r in newly}}
            graded = [by_id[r["question_id"]] for r in records]
            if args.benchmark == datasets.LONGMEMEVAL_S:
                aggregates[condition] = grade.aggregate_longmemeval(graded)
            else:
                aggregates[condition] = grade.aggregate_locomo(graded)
            _write_jsonl(graded_path, graded)

        run_info = {
            "benchmark": args.benchmark,
            "subset": args.subset,
            "conversations": len(conversations),
            "questions": n_questions,
            "answer_model": cfg.answer_model,
            "judge_model": cfg.judge_model,
            "max_items": cfg.max_items,
            "include_graph": cfg.include_graph,
            "inline_dates": args.inline_dates,
            "gnosis_base_url": cfg.gnosis_base_url,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        (out_dir / "results.json").write_text(
            json.dumps({"run": run_info, "aggregates": aggregates}, indent=2)
        )
        report_text = report.render_report(args.benchmark, aggregates, run_info)
        (out_dir / "report.md").write_text(report_text)
        print()
        print(report_text)
        print(f"results: {out_dir / 'results.json'}")

    gnosis.close()
    llm.close()
    return 0


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
