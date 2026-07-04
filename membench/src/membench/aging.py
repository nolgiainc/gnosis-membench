"""Memory-aging benchmark protocol: long-horizon supersession maintenance.

Nothing in the LOCOMO / LongMemEval harness measures whether a memory system
correctly *supersedes* facts that get updated or contradicted as simulated
time passes — it ingests a corpus once and asks immediately. This module adds
the aging protocol sketched in ``docs/gaps-abstention-maintenance.md`` (§"Membench
aging protocol").

Research basis (docs/gaps-abstention-maintenance.md):
- Deterministic read-time "newest wins" beats write-time bi-temporal
  invalidation: 78.0–94.8% vs Zep's 7.0% on MemoryAgentBench FactConsolidation
  (arXiv:2606.01435).
- Indiscriminate add-all accumulation *measurably degrades* accuracy as memory
  grows: 67.5% → 55.5% (arXiv:2505.16067).

The protocol has three phases, mirroring the main harness's
ingest → answer → grade shape but with deterministic, LLM-free scoring:

1. **generate** — a seeded synthetic dataset of users whose facts get UPDATED
   (3+ version chains), CONTRADICTED (2 versions, no explicit recency cue),
   stay STABLE (controls), or act as DISTRACTORS (independent same-word facts
   that must NOT be dropped by supersession).
2. **ingest** — the flattened per-fact timeline is fed to gnosis in strict
   time order, each version carrying its synthetic ``session_date`` in the add
   metadata (exactly how ``ingest.py`` dates units), reusing the gnosis add
   path so ingest-time extraction lands ``fact`` memories.
3. **probe** — after full ingest, each slot is queried ("what is X's current
   favorite color?"); the returned memories are scored *deterministically* by
   locating each fact value's rank in the ranked recall. No LLM judge is
   required for the headline metrics; an optional LLM answer+judge phase reuses
   the same value-containment check.

Metrics (see ``aggregate_aging``):
- supersession accuracy — probe surfaces the NEWEST value, ranked above any
  stale value (update + contradiction slots).
- stale-answer rate — an outdated value is returned/ranked above the current
  one ("worse than wrong").
- retention — stable control facts are still retrievable.
- false-supersession rate — independent distractor facts wrongly dropped.
- store-growth ratio — fact versions ingested / unique current facts.

Supersession-ON vs OFF is not a harness flag: point the harness at a gnosis
running with / without ``GNOSIS_READ_SUPERSESSION_ENABLED`` and label each run
(``--config-label``); the report renders the labelled runs side by side.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from typing import Any

from .config import Config
from .gnosis import GnosisClient

# Slot kinds.
UPDATE = "update"  # 3+ versions, explicit change cue; newest is current
CONTRADICTION = "contradiction"  # 2 versions, no "I changed" cue; newest is current
STABLE = "stable"  # single version, never changes — retention control
DISTRACTOR = "distractor"  # independent same-word fact — false-supersession guard

SUPERSEDING_KINDS = (UPDATE, CONTRADICTION)

# Synthetic clock: version N of a slot lands STEP_WEEKS apart so gnosis sees the
# updates spread across simulated months, not one sitting.
_BASE_DATE = datetime(2024, 1, 1, 9, 0)
_STEP_WEEKS = 3


def _step_date(step: int, user_index: int) -> str:
    """Deterministic session_date for a version at ``step``.

    Per-user minute offset keeps distinct users' same-step events from
    colliding while preserving global time order across users.
    """
    when = _BASE_DATE + timedelta(weeks=_STEP_WEEKS * step, minutes=user_index)
    return when.strftime("%Y/%m/%d (%a) %H:%M")


# ===========================================================================
# Dataset model
# ===========================================================================


@dataclass(frozen=True)
class FactVersion:
    step: int
    value: str
    statement: str  # the user utterance that asserts this value
    event_date: str  # synthetic session_date carried in add metadata


@dataclass(frozen=True)
class FactSlot:
    slot_id: str  # "<user_id>:<attribute_key>"
    kind: str
    subject: str  # user display name
    attribute: str  # human phrase, e.g. "favorite color"
    probe_question: str
    versions: tuple[FactVersion, ...]  # time-ordered

    @property
    def current_value(self) -> str:
        return self.versions[-1].value

    @property
    def stale_values(self) -> tuple[str, ...]:
        return tuple(v.value for v in self.versions[:-1])


@dataclass(frozen=True)
class AgingUser:
    user_id: str
    name: str
    slots: tuple[FactSlot, ...]


@dataclass(frozen=True)
class AgingDataset:
    seed: int
    users: tuple[AgingUser, ...]

    @property
    def slots(self) -> list[FactSlot]:
        return [slot for user in self.users for slot in user.slots]

    def counts(self) -> dict[str, int]:
        by_kind: dict[str, int] = {UPDATE: 0, CONTRADICTION: 0, STABLE: 0, DISTRACTOR: 0}
        versions = 0
        for slot in self.slots:
            by_kind[slot.kind] += 1
            versions += len(slot.versions)
        return {
            "users": len(self.users),
            "slots": len(self.slots),
            "fact_versions": versions,
            **{f"{k}_slots": v for k, v in by_kind.items()},
        }


# ===========================================================================
# Dataset generator (deterministic, seeded)
# ===========================================================================

_NAMES = (
    "Alice",
    "Bruno",
    "Chandra",
    "Dmitri",
    "Ewa",
    "Farah",
    "Goro",
    "Hana",
    "Ines",
    "Jamal",
    "Keira",
    "Liam",
)

# Update attributes: value chains (each >=3 mutually non-substring values so a
# newest-value substring match can't accidentally match a stale value).
_UPDATE_ATTRS = (
    (
        "favorite_color",
        "favorite color",
        "What is {name}'s current favorite color?",
        ("blue", "green", "purple", "amber", "crimson", "silver"),
    ),
    (
        "home_city",
        "home city",
        "What city does {name} currently live in?",
        ("Denver", "Seattle", "Austin", "Portland", "Boston", "Raleigh"),
    ),
    (
        "phone_model",
        "phone model",
        "What phone model does {name} use now?",
        ("Pixel-6", "Pixel-8", "iPhone-15", "GalaxyS24", "Nothing-Phone", "OnePlus-12"),
    ),
    (
        "cuisine",
        "favorite cuisine",
        "What is {name}'s current favorite cuisine?",
        ("Thai", "Ethiopian", "Korean", "Peruvian", "Lebanese", "Vietnamese"),
    ),
)

# Contradiction attribute: employer, asserted flatly at two dates (no recency cue).
_EMPLOYERS = ("Acme-Corp", "Beta-Corp", "Cygnus-Labs", "Delta-Systems", "Everest-Inc", "Fathom-AI")

# Stable controls: single value, never restated.
_STABLE_ATTRS = (
    (
        "birthplace",
        "birthplace",
        "Where was {name} born?",
        "was born in",
        ("Cleveland", "Tucson", "Fresno", "Albany", "Reno", "Mobile"),
    ),
    (
        "first_pet",
        "first pet's name",
        "What was {name}'s first pet's name?",
        "first pet was named",
        ("Rex", "Milo", "Biscuit", "Shadow", "Pepper", "Waffles"),
    ),
)

# Distractor: shares the word "favorite color" but a DIFFERENT subject
# (the user's partner), with its own distinct value pool. Must survive
# supersession of the user's own favorite-color chain.
_DISTRACTOR_COLORS = ("teal", "maroon", "ochre", "indigo", "beige", "coral")


def _update_statement(rng: Random, attribute: str, value: str, first: bool) -> str:
    if first:
        return f"My {attribute} is {value}."
    return rng.choice(
        (
            f"Actually, my {attribute} is now {value}.",
            f"I changed my mind — my {attribute} is {value} these days.",
            f"Update: my {attribute} is {value} now.",
        )
    )


def _make_update_slot(
    rng: Random, user_id: str, name: str, user_index: int, attr: tuple, offset: int, n_versions: int
) -> FactSlot:
    key, attribute, probe, pool = attr
    values = [pool[(offset + i) % len(pool)] for i in range(n_versions)]
    versions = tuple(
        FactVersion(
            step=i,
            value=v,
            statement=_update_statement(rng, attribute, v, first=(i == 0)),
            event_date=_step_date(i, user_index),
        )
        for i, v in enumerate(values)
    )
    return FactSlot(
        slot_id=f"{user_id}:{key}",
        kind=UPDATE,
        subject=name,
        attribute=attribute,
        probe_question=probe.format(name=name),
        versions=versions,
    )


def _make_contradiction_slot(
    rng: Random, user_id: str, name: str, user_index: int, offset: int
) -> FactSlot:
    v0 = _EMPLOYERS[offset % len(_EMPLOYERS)]
    v1 = _EMPLOYERS[(offset + 1) % len(_EMPLOYERS)]
    versions = (
        FactVersion(0, v0, f"I work at {v0}.", _step_date(0, user_index)),
        # Later date, flat assertion, no "I changed jobs" cue — pure recency test.
        FactVersion(2, v1, f"I work at {v1}.", _step_date(2, user_index)),
    )
    return FactSlot(
        slot_id=f"{user_id}:employer",
        kind=CONTRADICTION,
        subject=name,
        attribute="employer",
        probe_question=f"Where does {name} currently work?",
        versions=versions,
    )


def _make_stable_slot(
    user_id: str, name: str, user_index: int, attr: tuple, offset: int
) -> FactSlot:
    key, attribute, probe, verb, pool = attr
    value = pool[offset % len(pool)]
    versions = (FactVersion(0, value, f"I {verb} {value}.", _step_date(0, user_index)),)
    return FactSlot(
        slot_id=f"{user_id}:{key}",
        kind=STABLE,
        subject=name,
        attribute=attribute,
        probe_question=probe.format(name=name),
        versions=versions,
    )


def _make_distractor_slot(user_id: str, name: str, user_index: int, offset: int) -> FactSlot:
    value = _DISTRACTOR_COLORS[offset % len(_DISTRACTOR_COLORS)]
    statement = f"My partner's favorite color is {value}."
    versions = (FactVersion(1, value, statement, _step_date(1, user_index)),)
    return FactSlot(
        slot_id=f"{user_id}:partner_color",
        kind=DISTRACTOR,
        subject=name,
        attribute="partner's favorite color",
        probe_question=f"What is {name}'s partner's favorite color?",
        versions=versions,
    )


def generate_dataset(*, seed: int = 7, n_users: int = 8, update_versions: int = 3) -> AgingDataset:
    """Build a deterministic aging dataset.

    Per user (fixed mix, so counts scale linearly with ``n_users``):
      - 2 UPDATE chains       (``update_versions`` versions each, >=3)
      - 1 CONTRADICTION pair   (2 versions, no recency cue)
      - 2 STABLE controls      (birthplace + first pet)
      - 1 DISTRACTOR           (partner's favorite color — false-supersession guard)
    """
    if update_versions < 3:
        raise ValueError("update chains must have >=3 versions to test a real chain")
    if n_users < 1 or n_users > len(_NAMES):
        raise ValueError(f"n_users must be in 1..{len(_NAMES)}")
    rng = Random(seed)
    users: list[AgingUser] = []
    for u in range(n_users):
        name = _NAMES[u]
        user_id = f"u{u:02d}"
        nv = update_versions
        slots: list[FactSlot] = [
            _make_update_slot(rng, user_id, name, u, _UPDATE_ATTRS[0], offset=u, n_versions=nv),
            _make_update_slot(
                rng, user_id, name, u, _UPDATE_ATTRS[1 + (u % 3)], offset=u + 1, n_versions=nv
            ),
            _make_contradiction_slot(rng, user_id, name, u, offset=u),
            _make_stable_slot(user_id, name, u, _STABLE_ATTRS[0], offset=u),
            _make_stable_slot(user_id, name, u, _STABLE_ATTRS[1], offset=u),
            _make_distractor_slot(user_id, name, u, offset=u),
        ]
        users.append(AgingUser(user_id=user_id, name=name, slots=tuple(slots)))
    return AgingDataset(seed=seed, users=tuple(users))


# ===========================================================================
# Timeline & ingest
# ===========================================================================


@dataclass(frozen=True)
class TimelineEvent:
    event_key: str  # "<slot_id>#<step>" — resumable ingest identity
    user_id: str
    name: str
    slot_id: str
    kind: str
    event_date: str
    statement: str


def build_timeline(dataset: AgingDataset) -> list[TimelineEvent]:
    """Flatten every fact version into a single time-ordered ingest timeline."""
    events: list[TimelineEvent] = []
    for user in dataset.users:
        for slot in user.slots:
            for version in slot.versions:
                events.append(
                    TimelineEvent(
                        event_key=f"{slot.slot_id}#{version.step}",
                        user_id=user.user_id,
                        name=user.name,
                        slot_id=slot.slot_id,
                        kind=slot.kind,
                        event_date=version.event_date,
                        statement=version.statement,
                    )
                )
    # Strict time order (then slot_id) so gnosis observes updates chronologically.
    events.sort(key=lambda e: (e.event_date, e.slot_id, e.event_key))
    return events


def aging_user_id(user_id: str) -> str:
    return f"aging:{user_id}"


def aging_scope(cfg: Config, user_id: str, session_id: str) -> dict[str, str]:
    uid = aging_user_id(user_id)
    return GnosisClient.scope(
        tenant_id=cfg.tenant_id,
        space_id=cfg.space_id,
        agent_id=cfg.agent_id,
        session_id=f"{uid}:{session_id}",
        user_id=uid,
    )


def _ack(name: str) -> str:
    return "Thanks for letting me know."


def ingest_timeline(
    gnosis: GnosisClient,
    cfg: Config,
    events: list[TimelineEvent],
    state_path: Path,
    *,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Ingest the timeline in order via extraction-mode adds. Resumable by event_key.

    Each event is one user-turn + assistant-ack pair with ``session_date`` in
    metadata, matching ``ingest.py`` so gnosis dates the extracted fact.
    """
    state = _load_state(state_path)
    done: set[str] = set(state.get("done", []))
    written = 0
    started = time.time()
    for event in events:
        if event.event_key in done:
            continue
        scope = aging_scope(cfg, event.user_id, event.event_date.split(" ")[0])
        messages = [
            {"role": "user", "content": event.statement},
            {"role": "assistant", "content": _ack(event.name)},
        ]
        metadata = {
            "benchmark": "aging",
            "user_id": event.user_id,
            "slot_id": event.slot_id,
            "kind": event.kind,
            "session_date": event.event_date,
        }
        gnosis.add_memory(scope, messages, metadata=metadata)
        written += 1
        done.add(event.event_key)
        state["done"] = sorted(done)
        _save_state(state_path, state)
        log(f"  ingested {event.event_key} @ {event.event_date}: {event.statement!r}")
    return {
        "events": len(events),
        "written": written,
        "elapsed_s": round(time.time() - started, 1),
    }


# ===========================================================================
# Probe phase (deterministic retrieval-level scoring)
# ===========================================================================


def _first_rank(retrieved: list[dict[str, Any]], value: str) -> int | None:
    """Rank of the first retrieved memory whose content contains ``value``."""
    needle = value.lower()
    for item in retrieved:
        if needle in (item.get("content") or "").lower():
            return int(item["rank"])
    return None


def score_probe(record: dict[str, Any]) -> dict[str, Any]:
    """Score one probe record from its retrieved memories (LLM-free).

    ``record`` carries ``kind``, ``current_value``, ``stale_values`` and
    ``retrieved`` (a list of ``{rank, content, session_date}``). Returns the
    record enriched with rank + outcome fields.
    """
    retrieved = record["retrieved"]
    current_rank = _first_rank(retrieved, record["current_value"])
    stale_ranks = [
        r for r in (_first_rank(retrieved, v) for v in record["stale_values"]) if r is not None
    ]
    stale_rank = min(stale_ranks) if stale_ranks else None
    current_present = current_rank is not None
    stale_present = stale_rank is not None

    superseded: bool | None = None
    stale: bool | None = None
    if record["kind"] in SUPERSEDING_KINDS:
        # Newest wins iff the current value is present AND no stale value
        # outranks it.
        superseded = current_present and (not stale_present or current_rank < stale_rank)
        stale = stale_present and (not current_present or stale_rank < current_rank)

    return {
        **record,
        "current_rank": current_rank,
        "stale_rank": stale_rank,
        "current_present": current_present,
        "stale_present": stale_present,
        "superseded": superseded,
        "stale": stale,
        # stable retention / distractor false-supersession both hinge on the
        # slot's (sole) current value still being retrievable.
        "retained": current_present,
        "dropped": (record["kind"] == DISTRACTOR) and not current_present,
    }


def probe_record_for_slot(
    slot: FactSlot, user: AgingUser, retrieved: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "probe_id": slot.slot_id,
        "user_id": user.user_id,
        "name": user.name,
        "kind": slot.kind,
        "attribute": slot.attribute,
        "question": slot.probe_question,
        "current_value": slot.current_value,
        "stale_values": list(slot.stale_values),
        "retrieved": retrieved,
    }


def _retrieve(gnosis: GnosisClient, cfg: Config, user: AgingUser, slot: FactSlot) -> list[dict]:
    scope = aging_scope(cfg, user.user_id, "query")
    records = gnosis.search(scope, slot.probe_question, limit=cfg.max_items)
    out: list[dict[str, Any]] = []
    for rank, rec in enumerate(records):
        metadata = rec.get("metadata") or {}
        out.append(
            {
                "rank": rank,
                "content": rec.get("content") or "",
                "session_date": metadata.get("session_date"),
            }
        )
    return out


def probe_all(
    gnosis: GnosisClient,
    cfg: Config,
    dataset: AgingDataset,
    out_path: Path,
    *,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Probe every slot, streaming scored results to JSONL. Resumable by probe_id."""
    done: dict[str, dict[str, Any]] = {r["probe_id"]: r for r in read_jsonl(out_path)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with out_path.open("a") as out:
        for user in dataset.users:
            for slot in user.slots:
                if slot.slot_id in done:
                    results.append(done[slot.slot_id])
                    continue
                retrieved = _retrieve(gnosis, cfg, user, slot)
                scored = score_probe(probe_record_for_slot(slot, user, retrieved))
                results.append(scored)
                out.write(json.dumps(scored) + "\n")
                out.flush()
                log(f"  probed {slot.slot_id} ({slot.kind}): superseded={scored['superseded']}")
    return results


# ===========================================================================
# Aggregation & metrics
# ===========================================================================


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def aggregate_aging(scored: list[dict[str, Any]], store_growth: dict[str, Any]) -> dict[str, Any]:
    """Compute the five headline aging metrics from scored probes.

    - supersession_accuracy = superseded / (update + contradiction probes)
    - stale_answer_rate      = stale     / (update + contradiction probes)
    - retention              = retrievable stable controls / stable probes
    - false_supersession_rate= dropped distractors / distractor probes
    - retrieval_miss_rate     = superseding probes surfacing neither value
    - store_growth_ratio      = fact versions ingested / unique current facts
    """
    superseding = [r for r in scored if r["kind"] in SUPERSEDING_KINDS]
    stable = [r for r in scored if r["kind"] == STABLE]
    distractor = [r for r in scored if r["kind"] == DISTRACTOR]

    n_super = len(superseding)
    superseded = sum(1 for r in superseding if r["superseded"])
    stale = sum(1 for r in superseding if r["stale"])
    miss = sum(1 for r in superseding if not r["current_present"] and not r["stale_present"])

    return {
        "supersession_accuracy": _rate(superseded, n_super),
        "stale_answer_rate": _rate(stale, n_super),
        "retrieval_miss_rate": _rate(miss, n_super),
        "retention": _rate(sum(1 for r in stable if r["retained"]), len(stable)),
        "false_supersession_rate": _rate(
            sum(1 for r in distractor if r["dropped"]), len(distractor)
        ),
        "store_growth_ratio": store_growth["ratio"],
        "counts": {
            "superseding_probes": n_super,
            "superseded": superseded,
            "stale": stale,
            "retrieval_miss": miss,
            "stable_probes": len(stable),
            "distractor_probes": len(distractor),
            **store_growth,
        },
    }


def store_growth(dataset: AgingDataset) -> dict[str, Any]:
    """Fact versions ingested vs unique current facts (one per slot)."""
    counts = dataset.counts()
    versions = counts["fact_versions"]
    unique = counts["slots"]
    return {
        "fact_versions_ingested": versions,
        "unique_current_facts": unique,
        "ratio": round(versions / unique, 4) if unique else 0.0,
    }


# ===========================================================================
# Report
# ===========================================================================

_METRIC_ROWS = (
    ("supersession_accuracy", "supersession accuracy", "higher", "pct"),
    ("stale_answer_rate", "stale-answer rate", "lower", "pct"),
    ("retrieval_miss_rate", "retrieval miss rate", "lower", "pct"),
    ("retention", "retention (stable controls)", "higher", "pct"),
    ("false_supersession_rate", "false-supersession rate", "lower", "pct"),
    ("store_growth_ratio", "store-growth ratio", "n/a", "ratio"),
)


def render_aging_report(results_by_label: dict[str, dict[str, Any]], run_info: dict) -> str:
    """Render the aging report, one column per labelled config (ON vs OFF)."""
    labels = list(results_by_label)
    lines = [
        "# gnosis membench — memory-aging protocol",
        "",
        f"- seed: {run_info.get('seed')}, users: {run_info.get('users')}, "
        f"slots: {run_info.get('slots')}, fact versions: {run_info.get('fact_versions')}",
        f"- retrieval depth (limit): {run_info.get('max_items')}",
        f"- configs: {', '.join(labels)}",
        "",
        "| metric | want | " + " | ".join(labels) + " |",
        "|---|---|" + "---|" * len(labels),
    ]
    for key, label, want, fmt in _METRIC_ROWS:
        cells = []
        for lbl in labels:
            value = results_by_label[lbl].get(key, 0.0)
            cells.append(f"{value * 100:.1f}%" if fmt == "pct" else f"{value:.2f}×")
        lines.append(f"| {label} | {want} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Good looks like: high supersession accuracy, ~zero stale-answer rate, "
        "full retention, ~zero false-supersession, store-growth tracking the "
        "append-only fact count.",
        "",
        "Supersession-ON vs OFF is set on gnosis via "
        "`GNOSIS_READ_SUPERSESSION_ENABLED`; each column is one labelled run "
        "against a gnosis with the flag on/off.",
        "",
    ]
    return "\n".join(lines)


# ===========================================================================
# JSONL helpers (shared shape with run.py)
# ===========================================================================


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def dataset_to_json(dataset: AgingDataset) -> dict[str, Any]:
    return {
        "seed": dataset.seed,
        "counts": dataset.counts(),
        "users": [asdict(user) for user in dataset.users],
    }


def _load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ===========================================================================
# Orchestration (wired from run.py's `aging` subcommand)
# ===========================================================================

AGING_STAGES = ("ingest", "probe")


@dataclass(frozen=True)
class AgingArgs:
    seed: int = 7
    n_users: int = 8
    update_versions: int = 3
    config_label: str = "default"
    stages: tuple[str, ...] = AGING_STAGES
    out_dir: Path | None = None
    compare_with: Path | None = None  # a prior aging_results.json to render alongside


def run_aging(
    gnosis: GnosisClient,
    cfg: Config,
    args: AgingArgs,
    out_dir: Path,
    *,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Full aging run: generate -> (ingest) -> probe -> aggregate -> report."""
    dataset = generate_dataset(
        seed=args.seed, n_users=args.n_users, update_versions=args.update_versions
    )
    (out_dir / "dataset.json").write_text(json.dumps(dataset_to_json(dataset), indent=2))
    growth = store_growth(dataset)
    log(f"aging dataset: {dataset.counts()}")

    if "ingest" in args.stages:
        events = build_timeline(dataset)
        summary = ingest_timeline(gnosis, cfg, events, out_dir / "ingest_state.json", log=log)
        log(f"ingest complete: {summary}")

    scored: list[dict[str, Any]] = []
    if "probe" in args.stages:
        scored = probe_all(gnosis, cfg, dataset, out_dir / "probes.jsonl", log=log)

    metrics = aggregate_aging(scored, growth) if scored else {"store_growth_ratio": growth["ratio"]}

    results_by_label = {args.config_label: metrics}
    if args.compare_with and args.compare_with.exists():
        prior = json.loads(args.compare_with.read_text())
        for label, m in prior.get("results_by_label", {}).items():
            results_by_label.setdefault(label, m)

    run_info = {**dataset.counts(), "seed": args.seed, "max_items": cfg.max_items}
    payload = {"run": run_info, "results_by_label": results_by_label}
    (out_dir / "aging_results.json").write_text(json.dumps(payload, indent=2))
    report_text = render_aging_report(results_by_label, run_info)
    (out_dir / "aging_report.md").write_text(report_text)
    log("")
    log(report_text)
    return payload
