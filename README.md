# gnosis-membench

Memory-quality benchmark harness for [gnosis](../gnosis), our memory service.
It runs the two standard agent-memory benchmarks end-to-end against a live
gnosis instance and scores the answers with each benchmark's **official**
protocol, so the numbers are directly comparable to what mem0, Zep, A-Mem,
and the benchmark papers publish — and comparable to our own previous runs
(regression detection).

- **LongMemEval** ([arXiv 2410.10813](https://arxiv.org/abs/2410.10813),
  [repo](https://github.com/xiaowu0162/LongMemEval)) — 500 questions, each
  with its own ~40-session chat haystack (`longmemeval_s`, ~115k tokens).
  Categories: single-session-user / single-session-assistant /
  single-session-preference / multi-session / knowledge-update /
  temporal-reasoning, plus abstention (`_abs`) questions.
  Scored by the official LLM-judge prompts (used **verbatim** from
  [`src/evaluation/evaluate_qa.py`](https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py)).
- **LOCOMO** ([arXiv 2402.17753](https://arxiv.org/abs/2402.17753),
  [repo](https://github.com/snap-research/locomo)) — 10 very long two-person
  conversations, 1,986 QA pairs in 5 categories (single-hop, multi-hop,
  temporal, open-domain, adversarial). Scored with the official lexical
  metrics (Porter-stemmed token F1 with the official per-category dispatch,
  from [`task_eval/evaluation.py`](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py)),
  BLEU-1 (as reported by the mem0 paper), and a binary CORRECT/WRONG
  LLM-judge "J" score (mem0-style, categories 1–4; adversarial uses the
  official substring rule).

Both benchmarks are in active use (2026-07-04): **LOCOMO subset 3 is the
frozen dev-loop regression gate** (noise-saturated at the subset level — the
±2.3 J floor between identical configs exceeds every remaining subset lever;
the **full-LOCOMO, same-n competitor comparison is Run 23**, see the
saturation note and Run 23 in [RESULTS.md](RESULTS.md)) and **LongMemEval_S is the
primary optimization target**, run on a frozen 100-instance stratified
subset (question ids in `data/longmemeval_s_subset100.txt`,
regenerated deterministically by `membench/scripts/make_lme_subset100.py`)
with `gemini-embedding-001` (3072-dim) embeddings, gpt-5.5 extraction, and
the official judge prompts on a frozen gpt-5.5 judge. Both frozen configs
are specified precisely in [RESULTS.md](RESULTS.md).

## How it works

```
benchmark JSON ──ingest──▶ gnosis (/v1/memories, infer=true, per turn-pair)
question ───────retrieve─▶ gnosis (/v1/memory/context  OR  /v1/memories/search)
retrieved text ─answer───▶ LLM (sees ONLY the retrieved memory, never the raw history)
hypothesis ─────grade────▶ official scorer (LLM judge / F1 / BLEU-1)
                └──▶ results.json + report.md (paper-style category tables)
```

- One gnosis `user_id` per benchmark conversation, one `session_id` per
  benchmark session, one extraction-mode add per user+assistant turn-pair.
- Haystack session dates go into the add `metadata` (`session_date`);
  gnosis has no ingest-time timestamp override, so `--inline-dates` can
  additionally prefix turn text with the session date (helps
  temporal-reasoning; off by default because it mutates benchmark text).
- Two retrieval **conditions** are measured independently:
  `context` (`POST /v1/memory/context`) and `search`
  (`POST /v1/memories/search`, formatted with session dates from metadata).
- Answer prompts are the official ones: LongMemEval's "facts" reading
  template and LOCOMO's `QA_PROMPT`/`QA_PROMPT_CAT_5` (plus the abstention
  line the LOCOMO authors keep alongside them, which their category-5
  scorer depends on).

## Quick start

### 1. Stand up the stack

gnosis needs Neo4j and an OpenAI-compatible LLM+embedding endpoint
(LiteLLM in-cluster; locally, ollama's `/v1` works fine):

```bash
# local ollama option
ollama pull llama3.2:latest && ollama pull nomic-embed-text

cd stack
cp .env.example .env        # defaults point at host ollama; edit for LiteLLM
docker compose up --build -d
curl -s localhost:8080/ready   # {"status":"ready"}
```

The gnosis image builds from a sibling checkout of the gnosis repo
(override with `GNOSIS_CONTEXT` in `stack/.env`).

### 2. Run a benchmark

```bash
cd membench
uv sync

# datasets (LOCOMO ~2.8 MB from GitHub; LongMemEval_S ~277 MB from HuggingFace)
uv run membench download --benchmark locomo
uv run membench download --benchmark longmemeval_s

# answerer + judge LLM (any OpenAI-compatible endpoint)
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY=sk-...
export MEMBENCH_ANSWER_MODEL=gpt-4o-mini   # papers use gpt-4o-mini / gpt-4o
export MEMBENCH_JUDGE_MODEL=gpt-4o

# small trial first (1 conversation), then the full thing
uv run membench run --benchmark locomo --subset 1 --conditions context,search
uv run membench run --benchmark longmemeval_s --conditions context,search
```

Outputs land in `results/<benchmark>/<timestamp>/`:
`answers_<condition>.jsonl`, `graded_<condition>.jsonl`, `results.json`, and
`report.md` with per-category tables in the papers' format. Ingest and
answering are resumable (state files in the run directory); use
`--stages answer,grade` to reuse an already-ingested store and
`--stages grade` to re-score existing answers.

Key environment variables (see `membench/src/membench/config.py`):
`GNOSIS_BASE_URL`, `GNOSIS_TOKEN`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
`MEMBENCH_ANSWER_MODEL`, `MEMBENCH_JUDGE_MODEL`, `MEMBENCH_MAX_ITEMS`
(retrieval depth, default 20), `MEMBENCH_TENANT_ID` (must match gnosis's
`GNOSIS_TENANT_ID`, default `bromigos`), `MEMBENCH_INCLUDE_GRAPH`,
`MEMBENCH_CONCURRENCY`.

### Answer/grade concurrency

The answer and grade stages make one independent LLM call per question
(~497 answers + ~497 judge calls per condition, each ~2–4 s). They run in a
thread pool sized by `MEMBENCH_CONCURRENCY` (default `8`), overridable per run
with `--concurrency N`. Records still stream to `answers_<condition>.jsonl` /
`graded_<condition>.jsonl` as they complete (crash-safe + resumable) and are
always aggregated in question order regardless of completion order. At 8
workers each stage is roughly 8× faster — a full run's answer+grade drops from
~90 min to ~12 min. Use `--concurrency 1` for deterministic, single-threaded
debugging.

The grade stage never touches gnosis or embeddings (one short judge call per
question), so it can safely run hotter than the answer stage:
`--grade-concurrency 24` overrides just that stage.

Ingest parallelism (`--ingest-concurrency N`) pools sessions across ALL
conversations (per-session add ordering is preserved — extraction context
depends on it). With many small conversations (LongMemEval: one conversation
per question) this avoids draining the pool to a straggler tail at every
conversation boundary.

> **Keep it modest.** The answerer and judge share one rate-limited
> LiteLLM/OpenAI endpoint; going much above 8 in-flight requests tends to trip
> 429s (which then burn the client's retry budget) rather than go faster. Raise
> it only if your proxy's rate limits genuinely allow it. (Measured 2026-07-04:
> a local embedding call is ~40 ms and is NOT the ceiling — if transient 500s
> appear at higher concurrency, suspect the single `kubectl port-forward`
> tunnel to LiteLLM, not the embedder.)

> **Raw-ollama caveat (found live):** gnosis's graph-QA planner
> (`graph_query_qa.py`) passes `GNOSIS_LLM` verbatim to a plain OpenAI
> client, so LiteLLM-style names like `openai/llama3.2:latest` 404 against
> bare ollama and `/v1/memory/context` returns 500 whenever the graph
> section is requested. Everything else (extraction, embeddings, search)
> goes through the LiteLLM adapter and works. Set
> `MEMBENCH_INCLUDE_GRAPH=false` when gnosis points at a bare
> OpenAI-compatible endpoint; behind a real LiteLLM proxy, leave it on.

## Cost warning

LLM-judge grading is not free. LongMemEval = 500 judge calls per condition;
LOCOMO = ~1,540 judge calls per condition (categories 1–4) — plus one
answer-generation call per question, each carrying up to `MEMBENCH_MAX_ITEMS`
retrieved memories. A full two-condition LongMemEval + LOCOMO run is roughly
5k LLM calls. Ingest is the expensive part on the gnosis side: LongMemEval_S
is ~250k turns across all 500 haystacks — each an extraction LLM call inside
gnosis. Use `--subset N` liberally; published papers' judge of record is
gpt-4o (LongMemEval) / gpt-4o-mini (mem0's LOCOMO runs), so match those for
comparability.

## Our results

All official gnosis runs are recorded in **[RESULTS.md](RESULTS.md)** — the
canonical log with per-category tables, run configs, and deviations.
Two measurement scopes matter. **Subset-3 dev-loop gate** (Runs 1–22, 3 of
10 conversations) — the fast regression signal used during development:
**37.4 (Run 1) → ~71 (Run 18 reproducible; the recorded 74.8 was a
favorable-extraction outlier)**. **Full-LOCOMO (Run 23)** — the first
all-10-conversation measurement of the production config and the only
apples-to-apples competitor comparison: excl-adv J **66.9–68.9** (gpt-5.5 /
gpt-5.4-mini judges), **at parity with mem0 (66.88)**, below the
full-context ceiling (72.90). Defensible full-n leads: **single-hop** (both
axes), **temporal** and **adversarial** (judge-robust J), **multi-hop on the
judge-independent F1**; genuine weakness: **open-domain**. (The earlier
"74.8, above the ceiling, best overall" framing was a subset-3 artifact and
does not hold at full n.) Run 18 is the production config (fact extraction +
entity graph at write; adaptive routing + route-aware hardened
Chain-of-Note at read). The LongMemEval_S baseline (L-0) is pending.

## Published numbers to compare against

### LongMemEval_S accuracy (Zep paper, [arXiv 2501.13956](https://arxiv.org/abs/2501.13956), Tables 2–3)

| Question type | gpt-4o-mini full-ctx | gpt-4o-mini Zep | gpt-4o full-ctx | gpt-4o Zep |
|---|---|---|---|---|
| single-session-user | 81.4% | 92.9% | 81.4% | 92.9% |
| single-session-assistant | 81.8% | 75.0% | 94.6% | 80.4% |
| single-session-preference | 30.0% | 53.3% | 20.0% | 56.7% |
| temporal-reasoning | 36.5% | 54.1% | 45.1% | 62.4% |
| knowledge-update | 76.9% | 74.4% | 78.2% | 83.3% |
| multi-session | 40.6% | 47.4% | 44.3% | 57.9% |
| **overall** | **55.4%** | **63.8%** | **60.2%** | **71.2%** |

(The identical single-session-user row for both models is as printed in the
paper.) The LongMemEval paper itself ([arXiv 2410.10813](https://arxiv.org/abs/2410.10813),
Fig. 3b) reports gpt-4o at **0.870 with oracle retrieval** vs **0.606
full-context** on `longmemeval_s` — treat ~0.87 as the retrieval ceiling.

### LOCOMO (mem0 paper, [arXiv 2504.19413](https://arxiv.org/abs/2504.19413), Table 1; F1 / BLEU-1 / J, gpt-4o-mini)

| Method | Single-hop | Multi-hop | Temporal | Open-domain | Overall J |
|---|---|---|---|---|---|
| Mem0 | 38.72 / 27.13 / 67.13 | 28.64 / 21.58 / 51.15 | 48.93 / 40.51 / 55.51 | 47.65 / 38.72 / 72.93 | 66.88% |
| Mem0-graph | 38.09 / 26.03 / 65.71 | 24.32 / 18.82 / 47.19 | 51.55 / 40.28 / 58.13 | 49.27 / 40.30 / 75.71 | 68.44% |
| Zep | 35.74 / 23.30 / 61.70 | 19.37 / 14.82 / 41.35 | 42.00 / 34.53 / 49.31 | 49.56 / 38.92 / 76.60 | 65.99% |
| LangMem | 35.51 / 26.86 / 62.23 | 26.04 / 22.32 / 47.92 | 30.75 / 25.84 / 23.43 | 40.91 / 33.63 / 71.12 | 58.10% |
| OpenAI memory | 34.30 / 23.72 / 63.79 | 20.09 / 15.42 / 42.92 | 14.04 / 11.25 / 21.71 | 39.31 / 31.16 / 62.29 | 52.90% |
| A-Mem (mem0 rerun) | 20.76 / 14.90 / 39.79 | 9.22 / 8.81 / 18.85 | 35.40 / 31.08 / 49.91 | 33.34 / 27.58 / 54.05 | 48.38% |
| **Full-context baseline** | — | — | — | — | **72.90%** |
| **Gnosis Run 23** (full 10, F1/B1/J-gpt5.5) | 60.9 / 54.1 / 77.0 | 34.3 / 29.1 / 41.5 | 32.5 / 27.1 / 73.8 | 18.0 / 14.1 / 29.2 | **66.9%** (gpt5.5) / 68.9% (gpt5.4-mini) |
| _Gnosis Run 18_ (subset 3, J only — **not comparable-n**) | _82.0_ | _44.6_ | _91.1_ | _42.9_ | _74.8 / 76.7 (subset-3 gate)_ |

**Run 23 is the apples-to-apples comparison (same full n).** Defensible
**leads**: single-hop (J 77 vs mem0 67.13; **F1 60.9 vs 38.72**); temporal
(J 73.8 vs mem0-graph 58.13, judge-robust — its low F1 is a date-format
artifact, not a deficit); multi-hop on the **judge-independent F1** (34.3 vs
mem0 28.64) even though its J trails — the multi-hop J gap is dominated by
judge generosity (41.5 on gpt-5.5 → 49.6 on gpt-5.4-mini vs mem0 51.15).
Adversarial **83.9** (judge-robust; unpublished by mem0/Zep). **Trails**:
open-domain (J 29–31 vs Zep 76.6 / mem0 72.9 — a genuine full-n weakness).
**Overall excl-adv J 66.9–68.9 is at parity with mem0 (66.88)**, ties
mem0-graph (68.44), and sits below the full-context ceiling (72.90). The
subset-3 row is retained for history but compares our easy-3 against
everyone's full-10 and is not a competitive claim.

Letta's own blog run ([source](https://www.letta.com/blog/benchmarking-ai-agent-memory/))
reports **74.0%** on LOCOMO for a Letta filesystem agent (gpt-4o-mini). A-Mem's
paper ([arXiv 2502.12110](https://arxiv.org/abs/2502.12110)) reports its own
higher LOCOMO F1 numbers but with multi-hop/temporal column labels swapped
relative to mem0's table — cross-paper per-category comparisons in those two
categories are unreliable.

**Caveats when comparing:**

- Vendor-run numbers for *each other's* systems are contested: Zep's
  [rebuttal](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
  of the mem0 paper alleges misconfiguration and self-reports LOCOMO
  J = 75.14%; mem0 in turn disputed Zep's earlier LOCOMO claims. Treat all
  vendor-on-vendor rows as ±5-10 points.
- LOCOMO is short enough (~16–26k tokens) that **full context beats every
  memory system** (72.9 J) — it measures extraction fidelity, not long-horizon
  retrieval. LongMemEval is the harder, more diagnostic benchmark.
- Judge model matters: use gpt-4o (LongMemEval) / gpt-4o-mini (LOCOMO) to
  match published numbers; a different judge shifts absolute scores.

### What "good" looks like for gnosis

- **LongMemEval_S overall ≥ 60%** (full-context gpt-4o level) is table
  stakes; **≥ 71%** is Zep-level (published SOTA for a memory service);
  the oracle-retrieval ceiling is ~87%. Watch `temporal-reasoning` and
  `single-session-preference` — every memory system is weakest there.
- **LOCOMO overall J (excl. adversarial) ≥ 60%** is competitive;
  **≥ 67–68%** matches mem0; ≥ 73% beats the full-context baseline.
- **Regressions:** with 500 questions, an overall LongMemEval drop of ~4+
  points between runs of the same config is signal, not noise; per-category
  (50–130 questions) needs ~8+ points.
- The gap between the `context` and `search` conditions tells you whether
  gnosis's context assembly is adding value over raw ranked recall.

## Aging protocol

The LOCOMO / LongMemEval harness ingests a corpus once and asks immediately, so
it never measures **long-horizon maintenance**: whether gnosis correctly
*supersedes* facts that get updated or contradicted as time passes. The aging
protocol (`membench aging`, `src/membench/aging.py`) fills that gap. Research
basis: `docs/gaps-abstention-maintenance.md` — deterministic read-time
"newest-wins" beats write-time bi-temporal invalidation (78–94.8% vs 7% on
MemoryAgentBench FactConsolidation, arXiv:2606.01435), and indiscriminate
add-all accumulation degrades accuracy 67.5→55.5 as memory grows
(arXiv:2505.16067).

**What it measures.** A seeded synthetic dataset gives each user facts that
either get UPDATED (3+ version chains, e.g. favorite color blue→green→purple),
CONTRADICTED (two flat assertions at different dates, no "I changed" cue, e.g.
works at Acme-Corp then Beta-Corp), stay STABLE (controls that never change), or
act as DISTRACTORS (independent same-word facts — the user's *partner's*
favorite color — that must NOT be dropped when the user's own color chain is
superseded). Every fact version carries a synthetic `session_date` (weeks
apart) passed via add metadata exactly as `ingest.py` dates units. The timeline
is ingested in strict time order; then each slot is probed ("what is X's
current favorite color?") and scored **deterministically from the returned
memories, no LLM judge**:

| metric | want | how it's computed |
|---|---|---|
| supersession accuracy | high | probe surfaces the newest value, ranked above any stale value |
| stale-answer rate | ~0 | an outdated value is returned / ranked above the current one |
| retention (stable controls) | full | stable facts still retrievable |
| false-supersession rate | ~0 | independent distractor facts wrongly dropped |
| store-growth ratio | tracks fact count | fact versions ingested / unique current facts |

**Good looks like:** high supersession accuracy, ~zero stale-answer rate, full
retention, ~zero false-supersession, store-growth tracking the append-only fact
count.

**Running it live (pending).** The live run happens *after gnosis ships
read-time supersession*. Supersession-ON vs OFF is not a harness flag — point
the harness at a gnosis started with / without `GNOSIS_READ_SUPERSESSION_ENABLED`
and label each run:

```bash
cd membench
# with gnosis running supersession OFF:
uv run membench aging --config-label supersession_off --out results/aging/off
# restart gnosis with GNOSIS_READ_SUPERSESSION_ENABLED=true, then:
uv run membench aging --config-label supersession_on --out results/aging/on \
  --compare-with results/aging/off/aging_results.json
```

The second run renders both configs side by side in `aging_report.md`. Tune the
dataset size with `--users N` and chain length with `--update-versions K`
(deterministic per `--seed`). All phases are resumable (JSONL + state files) like
the main harness.

## Repo layout

```
stack/compose.yaml    neo4j 5.26 + gnosis (built from ../../gnosis), env-wired
                      to any OpenAI-compatible endpoint (LiteLLM / ollama /v1)
membench/             uv project
  src/membench/
    datasets.py       download + load + normalize both benchmarks
    ingest.py         turn-by-turn extraction-mode adds into gnosis
    answer.py         retrieve (context|search) + answer with official prompts
    grade.py          official scoring (verbatim LongMemEval judge prompts,
                      LOCOMO F1/BLEU-1/judge)
    report.py         paper-style markdown tables
    aging.py          memory-aging protocol: synthetic supersession maintenance
    run.py            CLI: membench download | membench run | membench aging
  tests/              fixture-based unit tests (loaders, graders, request shapes)
```

## Development

```bash
cd membench
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
```
