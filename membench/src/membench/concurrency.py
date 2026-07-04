"""Streaming, order-preserving parallel map for the benchmark harness.

Both the answer stage and the grade stage are embarrassingly parallel: each
record's work (one gnosis retrieval + one answerer call, or one judge call) is
independent of every other, yet the old code ran them in serial
``for record in records:`` loops over a synchronous ``ChatClient``. This helper
runs ``work_fn`` across a thread pool while preserving the three properties
those loops had:

- resumability: records already present in ``out_path`` (a JSONL file) are
  loaded up front and their items skipped, so a re-run only does the
  outstanding work;
- crash-safety: each result is appended to ``out_path`` and flushed the moment
  its future completes, under a lock, so a crash keeps every finished record;
- deterministic order: results are returned in the original ``items`` order
  regardless of completion order, because downstream aggregation and the
  rewritten JSONL expect it.

``workers <= 1`` runs everything inline on the calling thread (no executor), so
serial debugging behaves exactly like the old loops.

Thread-safety note: callers share one synchronous ``ChatClient`` /
``GnosisClient`` (``httpx.Client``), which is safe for concurrent requests.
``ChatClient`` also mutates a ``_unsupported_params: dict[str, set[str]]`` on
400s, but only ever does set-adds of a fixed param name for a model key —
idempotent and benign under races (worst case: two threads each eat one
redundant 400 before the set converges). No locking is needed there.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def map_streaming[T](
    items: Iterable[T],
    work_fn: Callable[[T], dict[str, Any]],
    *,
    out_path: Path | None = None,
    key_fn: Callable[[T], str],
    workers: int = 1,
    done: Callable[[dict[str, Any]], str] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Run ``work_fn`` over ``items`` in parallel, streaming and order-preserving.

    Args:
        items: the input records/work items (materialised to preserve order).
        work_fn: ``item -> record`` (dict); the parallel unit of work.
        out_path: JSONL file to append completed records to and to resume from.
            ``None`` disables both (streaming is left to ``on_result``).
        key_fn: ``item -> key``; identifies an item for resume/order matching.
        workers: thread-pool size; ``<= 1`` runs serially on this thread.
        done: ``record -> key`` for records loaded from ``out_path``; required
            for resume when ``out_path`` is given.
        on_result: called (under the write lock) with each newly computed record
            as its future completes — never for already-done, resumed records.
        log: progress sink (unused here; callers usually log via ``on_result``).

    Returns:
        Every item's record in the original ``items`` order, resumed records
        included.
    """
    items = list(items)
    done_records: dict[str, dict[str, Any]] = {}
    if out_path is not None and out_path.exists():
        if done is None:
            raise ValueError("map_streaming: out_path given without a `done` key function")
        with out_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                done_records[done(record)] = record

    pending = [(i, item) for i, item in enumerate(items) if key_fn(item) not in done_records]
    results: dict[int, dict[str, Any]] = {}
    lock = threading.Lock()

    out = None
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = out_path.open("a")

    def handle(index: int, record: dict[str, Any]) -> None:
        # Serialize file appends and the on_result callback so a shared file
        # handle / callback stays crash-safe under concurrent completions.
        with lock:
            results[index] = record
            if out is not None:
                out.write(json.dumps(record) + "\n")
                out.flush()
            if on_result is not None:
                on_result(record)

    try:
        if workers <= 1:
            for index, item in pending:
                handle(index, work_fn(item))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(work_fn, item): index for index, item in pending}
                for future in as_completed(futures):
                    handle(futures[future], future.result())
    finally:
        if out is not None:
            out.close()

    ordered: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        key = key_fn(item)
        ordered.append(done_records[key] if key in done_records else results[index])
    return ordered
