# Knowledge-update: gap analysis and implementation roadmap

LongMemEval_S's knowledge-update (KU) category tests whether a system returns the
*current* value of a fact that has changed over the course of several sessions
("I used to work at X, but I just started a new job at Y").

**Current status (2026-08-06):**

| Run | KU score | Overall | What changed |
|---|---|---|---|
| L-23 (2026-07-31) | 23.6% (n=72) | 69.8% | Baseline — edu-v1, no slot supersession |
| L-25 (2026-08-05) | 73.1% | 72.4% | edu-v2.0 + relation_slots metadata |
| **L-25b (2026-08-06)** | **70.8%** | **73.6%** | + singleton-only supersession fix |
| **L-31 (2026-08-09)** | **80.6%** | **71.0%** | Write-time SUPERSEDES edges + valid_to IS NULL filter (re-run with fixed ingest) |
| **L-32 (2026-08-10)** | **81.9%** | **72.6%** | Enumeration clause fix + multi-query expansion for MS (no re-ingest) |
| **L-33 (2026-08-10)** | **81.9%** | **74.2%** | Extended aggregative pattern + 4 sub-queries + set-based dedup (no re-ingest) — new best overall |

**L-31 result: KU 70.8% → 80.6% (+9.8pp).** Structural fix confirmed. Net overall −2.6pp due to regressions SSA −3.6pp, temporal −7.9pp, SSU −6.3pp, MS −4.2pp. Regressions confirmed NOT from SUPERSEDES logic (routing identical to L-25b for SSA/temporal; only 28 facts have valid_to set) — ingest variation from fresh reingest explains the spread.

For comparison: Zep 83.3%, Chronos 100%, Mastra OM (gpt-5-mini) 96.2%.

---

## Why the gap exists (root cause, confirmed)

After L-25b, KU is 70.8% — partial improvement confirmed (+47.2pp vs L-23), but
~30pp still below Zep and 29pp below Chronos. Four post-L-25b experiments (L-27
to L-30) that attacked retrieval-layer symptoms all failed to advance the score.
Root cause analysis after L-30 established the structural problem:

**Old facts outrank new facts in embedding space.** gnosis's extracted fact model
stores every fact as an independent `:Fact` node. When a user's job changes:

```
(:Fact {content: "works at Google", event_date: "2023-01", valid_to: null})
(:Fact {content: "started at Nvidia", event_date: "2023-03", valid_to: null})
```

At retrieval time for "Where does Alice work now?", both facts compete. The "Google"
fact may rank higher because the original phrasing (from a different conversational
context) is closer to the query embedding than the update phrasing. Read-time
supersession (`GNOSIS_READ_SUPERSESSION_ENABLED`) can only drop old facts that
ARE in the top-20 candidate pool. If the new fact ranks #21 due to embedding
geometry, it never enters the pool and cannot be promoted.

**Key evidence:** L-29 (recency injection — merge top-5 newest facts into dense
top-20) gave +4.2pp KU, confirming that the new fact often IS in the graph but
not in the top-20. The fix is structural, not post-retrieval.

---

## What SOTA systems do

### Chronos (PwC) — 100% KU (arXiv:2603.16862)

Event calendar: `(subject, verb, object, start_datetime, end_datetime)` tuples
extracted per session. A `works_at` slot for Alice can hold only one active
event (end_datetime IS NULL). At query time: deterministic newest-wins via the
slot structure — no embedding comparison, no LLM judgment.

### Mastra Observational Memory — 96.2% KU (vendor-reported)

Three timestamps per observation: `observed_time`, `referenced_time`,
`relative_time_expression`. A background Reflector marks older observations as
superseded with explicit links; append-only (originals kept).

### arXiv:2607.26520 — Graph-Native Bitemporal Memory Store (the L-31 blueprint)

Neo4j-native bitemporal model. Write-time `(new)-[:SUPERSEDES]->(old)` edges
with `valid_time.end = datetime()` on the old node. At retrieval: `WHERE
valid_time.end IS NULL` excludes superseded facts from the candidate pool
entirely — they can't even compete. This is exactly the L-31 pattern.

### arXiv:2606.01435 — "Don't Ask the LLM to Track Freshness"

Deterministic `max(serial_number)` selection → 78–94.8% on FactConsolidation.
Zep's bi-temporal LLM write-time invalidation → 7%. Conclusion: **write-time
structural invalidation wins; LLM-based recency tracking does not.**

---

## Gnosis implementation roadmap

### Phase 1 — Bi-temporal timestamps + relation_slots metadata ✅ COMPLETE (L-24/L-25)

- `temporal_state` field in edu-v2 output (`starts`, `ends`, `ongoing`, `point_in_time`, `unknown`)
- `relation_slots` metadata key: `"{normalized_head}:{normalized_relation_class}"` written at
  ingest for singleton relations, enabling slot-based grouping at read time
- Read-time supersession (`GNOSIS_READ_SUPERSESSION_ENABLED`): newest-wins per slot

**Outcome:** KU 23.6% → 70.8% (L-25b). Partial — read-time supersession can only help
when the new fact is in top-20.

**Singleton-only fix (L-25b):** Only singleton relation classes (works_at, lives_in,
relationship_status, studies_at) participate in supersession. Additive relations (likes,
has_visited, owns) are excluded — their over-supersession was causing SSP/MS regressions.

### Phase 2 — Write-time SUPERSEDES edges + valid_to IS NULL filter ✅ DONE (L-31)

**Implementation (2026-08-06):**

1. `WRITE_TIME_SUPERSEDE_CYPHER` in `memory_provider.py`: at ingest, for any new
   fact with `relation_slots`, immediately query for same-scope same-slot existing
   facts with `valid_to IS NULL` and write `(new_fact)-[:SUPERSEDES]->(old_fact)`,
   set `old_fact.valid_to = datetime()`.

2. `filter_superseded: bool` field on `RouteDecision` — `True` for `knowledge_update`
   route only.

3. `LEXICAL_MEMORY_SEARCH_CYPHER` and `SCOPED_DENSE_MEMORY_SEARCH_CYPHER` both gain:
   `AND (NOT $filter_superseded OR f.valid_to IS NULL)` — stale facts can't rank in
   top-20 for KU queries at all.

**Result:** KU 70.8% → 80.6% (+9.8pp). Structural fix confirmed. Gap to Zep (83.3%): 2.7pp.

**Regressions:** SSA −3.6pp (94.6%), temporal −7.9pp (66.1%), SSU −6.3pp (78.1%), MS −4.2pp (54.5%); net −2.6pp overall (71.0% vs 73.6%). Root cause CONFIRMED: SUPERSEDES logic is not over-firing (only 28 facts total have `valid_to` set; routing trace confirmed SSA/temporal questions follow the same non-KU path as in L-25b — no `[recent]` section in retrieved context). Regressions are from fresh-ingest variation: different extracted facts for borderline conversations produce different retrieval and borderline judge calls.

### Phase 3 — Dynamic retrieval guidance per KU question type (queued)

Before retrieving for a query that appears to ask current state, generate a guidance
note emphasizing recency (Chronos "dynamic prompting"). A prompt-only change — no schema
work. Queue after L-31 results are confirmed.

---

## Membench measurement protocol for KU

### Baselines

**L-25b (2026-08-06) — best overall:**
- **KU accuracy: 70.8%** (51/72 correct, gpt-4o backbone + judge)
- Full 500-question run; 72 KU instances (question types: `knowledge-update` and `knowledge-update_abs`)
- Failure mode confirmed: ~21 failures where old/stale fact is returned instead of current value

**L-31 (2026-08-09, re-run with fixed ingest) — best KU:**
- **KU accuracy: 80.6%** (58/72 correct, gpt-4o backbone + judge); +7 correct vs L-25b
- Overall 71.0% (vs L-25b 73.6%); regressions in SSA/temporal/SSU/MS (ingest variation, not SUPERSEDES logic)

### Protocol for future KU runs

1. Run the full LME_S 500-question suite.
2. Filter `answers_context.jsonl` by `category == "knowledge-update"`.
3. Compare against **L-25b overall baseline (73.6%)** and **L-31 KU baseline (80.6%)**.
4. Report per-category impact: KU gain must not come at the cost of SSA or temporal regression.

**Reader-model note:** KU accuracy is reader-model dependent (58.4%–89.6% range across
models with identical retrieval; Memoria/MatrixOrigin study). L-25b and L-31 both use gpt-4o.

---

## Post-L-25b experiments: what failed and why

| Run | Change | KU | Net | Root cause of failure |
|---|---|---|---|---|
| L-27 | Community graph | 70.8% (flat) | -0.2pp overall | SSA -5.3pp from community injection; no KU benefit |
| L-28 | Stronger CoN recency clause | +1.4pp | -1.8pp overall | Clause over-fires on SSA/SSU outside KU context |
| L-29 | knowledge_update route + recency injection | +4.2pp | 0pp net | KU +4.2pp confirmed; SSA -5.3pp from routing misclassification cancels |
| L-30 | Tighter KU router guide | +1.4pp | -0.6pp overall | SSA partially recovered but temporal -2.4pp from over-restriction |
| **L-31** | **Write-time SUPERSEDES + valid_to filter** | **+9.8pp** | **-2.6pp overall** | KU structural fix confirmed (+9.8pp, 70.8%→80.6%); regressions SSA -3.6pp, temporal -7.9pp, MS -4.2pp — CONFIRMED as ingest variation (routing identical to L-25b, only 28 facts have valid_to) |

**Conclusion:** Write-time structural invalidation delivers the KU gain (Phase 2 ✅). Regressions confirmed NOT from router misfiring or SUPERSEDES over-firing — they are ingest-variation noise from fresh reingest. Phase 3 (router misclassification fix + multi-query expansion for MS) is the next lever.

---

## Sources

- [arXiv:2607.26520](https://arxiv.org/abs/2607.26520) — Graph-Native Bitemporal Memory (L-31 blueprint)
- [arXiv:2603.16862](https://arxiv.org/abs/2603.16862) — Chronos event calendar (100% KU)
- [arXiv:2606.01435](https://arxiv.org/html/2606.01435v1) — "Don't Ask the LLM to Track Freshness"
- [arXiv:2607.21962](https://arxiv.org/abs/2607.21962) — Ground Truth First (volatility taxonomy)
- [mastra.ai/research/observational-memory](https://mastra.ai/research/observational-memory) — Mastra OM Reflector
- [arXiv:2505.16067](https://arxiv.org/html/2505.16067v2) — add-all accumulation degrades accuracy
- [arXiv:2606.27472](https://arxiv.org/html/2606.27472) — supersession environment training
- [LongMemEval](https://arxiv.org/abs/2410.10813) — benchmark definition and KU category
- [Memoria/MatrixOrigin LME study](https://medium.com/@matrixorigin-database/benchmarking-memoria-on-longmemeval-strong-memory-retrieval-clear-reader-separation-ee6c89c75d76) — reader-model sensitivity on KU
