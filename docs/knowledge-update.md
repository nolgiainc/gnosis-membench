# Knowledge-update: gap analysis and implementation roadmap

LongMemEval_S's knowledge-update (KU) category tests whether a system returns the
*current* value of a fact that has changed over the course of several sessions
("I used to work at X, but I just started a new job at Y"). This is gnosis's
confirmed weakest axis.

**L-23 confirmed result (2026-07-31): 23.6% on 72 KU questions (full-500 run).**

For comparison: Zep 83.3%, Chronos 100%, mem0 not published. The gap to Zep is
~60 percentage points — the single largest improvement opportunity in the L-23 profile.

*Earlier measurements:* A 100-question stratified subset showed ~72.7% KU. That figure
was not representative — the subset's 17 KU instances happened to be the easier cases.
The full-500 run at 23.6% (72 instances) is the authoritative number.

---

## Why the gap exists

gnosis's extracted fact model stores every `edu-v1` fact unit as an independent
`:Fact` node with an `event_date` field (when the fact occurred). When a user's
location changes, two Fact nodes exist:

```
(:Fact {content: "lives in Seattle", event_date: "2023-01"})
(:Fact {content: "moved to Austin", event_date: "2023-03"})
```

At read time, both facts rank in the vector index with similar similarity scores
for "Where does Alice live?" — the "Seattle" fact may rank higher on some embedding
distances than "Austin" because the exact phrasing is closer. There is no mechanism
that says the earlier fact is superseded.

`GNOSIS_READ_SUPERSESSION_ENABLED` performs approximate newest-wins at retrieval
time, but it operates heuristically (same entity + contradictory predicate) without
explicit graph links and without validated effectiveness on LME_S.

---

## What SOTA systems do

### Chronos (PwC) — 100% KU with event calendar (arXiv:2603.16862)

**Event calendar structure:** `(subject, verb, object, start_datetime, end_datetime, lexical_aliases[])` tuples extracted per conversation, separate from the semantic fact store.

When a user changes jobs:
- Turn 10 (session 3): "I started at Nvidia last week" → event `{subject: Alice, verb: works-at, object: Nvidia, start: 2024-03, end: null}`
- Turn 2 (session 1): "I work at Google" → event `{subject: Alice, verb: works-at, object: Google, start: 2023-01, end: 2024-03 (inferred from supersession)}`

At query time for "Where does Alice work?", Chronos retrieves the event with the latest `start_datetime` for the (subject, works-at) slot deterministically — no LLM judgment involved.

### Mastra Observational Memory — 96.2% KU via reflector (vendor-reported)

Three timestamps per observation: `observed_time`, `referenced_time`, `relative_time_expression`. A background *Reflector* periodically marks older observations as superseded with explicit links; it never deletes originals (append-only).

### arXiv:2606.01435 — "Don't Ask the LLM to Track Freshness"

Deterministic `max(serial_number)` selection (BM25 top-10 → LLM candidate match → pick newest) → **78–94.8%** on FactConsolidation.

Zep's bi-temporal LLM-based write-time invalidation → **7.0%** on the same task.

**Conclusion:** deterministic recency wins. Write-time LLM deletion of old facts is both error-prone and information-destroying.

---

## Gnosis roadmap for KU

### Phase 1 (next gnosis PR): Bi-temporal timestamps on every fact

Add `valid_from` and `valid_to` fields to the `:Fact` node schema. The extractor
(edu-v1) already extracts `event_date` as a point-in-time; extend it to detect
interval-bearing facts:

- "I started working at Nvidia" → `valid_from = event_date, valid_to = null`
- "I quit my job at Google" → `valid_to = event_date` (on the existing Google fact
  if linkable, or stored as a new invalidation signal)

Extraction prompt change (edu-v2): add a `temporal_state` field to the output
schema with values `point_in_time | starts | ends | ongoing | unknown`. The
extractor also emits optional `supersedes_hint` when the text explicitly indicates
a change ("used to", "no longer", "just started").

**Cost:** extraction prompt change + schema field addition. No backend behavioral
change yet.

### Phase 2: Explicit SUPERSEDES edges in the entity graph

After extraction, when a new fact carries `temporal_state=starts` or `ends` for
the same (entity, relation_class) as an existing fact with a later `event_date`,
write a `(:Fact)-[:SUPERSEDES]->(:Fact {id: older_fact_id})` edge.

At read time, filter superseded facts from the candidate pool (or down-rank them
below any fact that supersedes them). This is the structural equivalent of Chronos's
event calendar slot-selection, expressed in Neo4j.

**Cypher sketch:**
```cypher
// Flag a fact as superseded:
MATCH (new:Fact {id: $new_id}), (old:Fact {id: $old_id})
MERGE (new)-[:SUPERSEDES]->(old)
ON CREATE SET old.superseded_at = datetime()

// At retrieval: exclude facts that have been superseded:
MATCH (f:Fact)-[:MENTIONS]->(e:Entity {tenant_id: $tid, user_id: $uid, normalized: $entity})
WHERE NOT EXISTS { (f)<-[:SUPERSEDES]-(:Fact) }
RETURN f ORDER BY f.event_date DESC
```

**Cost:** extractor prompt (edu-v2 `supersedes_hint`), one Cypher write per
detected supersession, read-path filter change.

### Phase 3 (optional): Dynamic retrieval guidance for KU queries

Before retrieving for a query that appears to ask about a current state ("Where
does X work now?", "What is Y's current position?"), generate a retrieval guidance
note that emphasizes recency: "Pay close attention to the most recent employment
events, especially any job changes or new start dates." Use the guidance as an
additional BM25 query.

This is the Chronos "dynamic prompting" technique and is a pure prompt-engineering
change (no schema work).

---

## Membench measurement protocol for KU

### Confirmed L-23 baseline (2026-07-31)

- **Overall KU accuracy: 23.6%** (17/72 correct, Claude-Sonnet-4-6 backbone + judge)
- Full 500-question run; 72 KU instances (`question_type == "knowledge-update"`, including
  the abstention variants, whose `question_id` ends in `_abs`)
- Failure mode confirmed: gnosis returns the superseded/earlier value instead of the
  current one. The more recent fact is present in the graph but ranks lower than the
  older, semantically-similar fact at retrieval time.

### Protocol for future KU runs

1. Run the full LME_S 500-question suite (or at minimum the 72 KU instances).
2. Filter `answers_context.jsonl` by `category == "knowledge-update"` (includes both
   standard and abstention variants).
3. Compare against L-23 baseline (17/72 = 23.6%).

For rapid iteration during KU-targeted development:
- Extract the 72 KU question IDs from the dataset: `question_type == "knowledge-update"`
  (hyphenated, as in the raw LongMemEval JSON and `load_longmemeval`); the abstention
  variants are the subset of those whose `question_id` ends in `_abs`
- Run ingest + retrieval only for those conversations (significant cost reduction)
- Use the Claude backbone approach (no inference key needed — runs via Claude Desktop subagents)

**Reader-model note:** LME_S KU accuracy is known to be reader-model dependent (Memoria
study: 58.4%–89.6% range across models with identical retrieval). L-23's 23.6% uses
Claude-Sonnet-4-6. After implementing SUPERSEDES edges (L-24), re-run with the same
model to isolate retrieval improvement from reader effect.

---

## Sources

- [arXiv:2603.16862](https://arxiv.org/abs/2603.16862) — Chronos event calendar
- [arXiv:2606.01435](https://arxiv.org/html/2606.01435v1) — "Don't Ask the LLM to Track Freshness"
- [mastra.ai/research/observational-memory](https://mastra.ai/research/observational-memory) — Mastra OM Reflector
- [arXiv:2505.16067](https://arxiv.org/html/2505.16067v2) — add-all accumulation degrades accuracy
- [arXiv:2606.27472](https://arxiv.org/html/2606.27472) — supersession environment training
- [LongMemEval](https://arxiv.org/abs/2410.10813) — benchmark definition and KU category
- [Memoria/MatrixOrigin LME study](https://medium.com/@matrixorigin-database/benchmarking-memoria-on-longmemeval-strong-memory-retrieval-clear-reader-separation-ee6c89c75d76) — reader-model sensitivity on KU
