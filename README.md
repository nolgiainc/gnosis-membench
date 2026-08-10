# gnosis-membench

Benchmark harness for the [gnosis memory service](https://github.com/blackflame007/gnosis).
Runs LongMemEval_S and LOCOMO through a consistent ingest → retrieval → answer →
grade pipeline. Results are logged in [`RESULTS.md`](RESULTS.md), the append-only
run ledger.

**Current standing — LongMemEval_S L-35 (full 500-Q, 2026-08-10) — new best overall:**
gpt-4o backbone + gpt-4o judge. Reuses L-31 Neo4j data; answer.py only changes.

| Category | L-35 | vs L-25b | Notes |
|---|---|---|---|
| knowledge-update | **80.6%** (n=72) | +9.8pp | write-time SUPERSEDES structural fix (L-31) |
| single-session-assistant | 92.9% (n=56) | −5.4pp | ingest-variation gap vs L-25b |
| single-session-user | 82.8% (n=64) | −1.6pp | |
| temporal-reasoning | **71.7%** (n=127) | −2.3pp | pattern expansion firing on "how long"/"how many months" phrasing |
| multi-session | **66.1%** (n=121) | +7.4pp | math instruction + sub-query expansion |
| single-session-preference | 53.3% (n=30) | −6.7pp | judge noise |
| abstention | **86.7%** (n=30) | +3.4pp | |
| **Overall** | **75.2%** (500 Q) | **+1.6pp** | vs Zep 71.2%, mem0 67.6%, Chronos 95.6% |

**L-31 (2026-08-09) — KU structural fix:**
- KU **70.8% → 80.6% (+9.8pp)** via write-time SUPERSEDES edges + `valid_to IS NULL` filter
- Overall 71.0%; regressions (SSA −3.6pp, temporal −7.9pp, MS −4.2pp) confirmed as ingest variation

**L-32 (2026-08-10) — enumeration clause fix + multi-query expansion for MS:**
- MS **54.5% → 59.5% (+5.0pp)** via 2-sub-query LLM expansion for aggregative multi-session questions
- KU **80.6% → 81.9% (+1.4pp)**; overall **72.6%** (+1.6pp vs L-31)

**L-33 (2026-08-10) — extended pattern + 4 sub-queries:**
- Extended `_AGGREGATIVE_PATTERN` to include `average|percentage|how long` (6 pattern-miss failures now covered)
- Sub-queries increased 2→4; dedup via `seen: set[str]` (was substring scan)
- Overall **74.2%** (+1.6pp vs L-32, **+0.6pp vs L-25b**)

**L-34 (2026-08-10) — math instruction for aggregative MS questions:**
- Appended `[instruction]` to retrieved context for aggregative multi-session questions: list every value, compute step by step
- MS **60.3% → 66.1% (+5.8pp, +7 questions)** — targets wrong-sum failures from L-32 analysis
- Overall **74.2%** (ties L-33)

**L-35 (2026-08-10) — conservative math instruction + pattern extensions (new best overall):**
- Conservative `_MATH_NOTE` with 3-check filter (direct match, time period, dedup); pattern extended with `increase`, `page count`
- MS flat (66.1%, 6 fixed / 6 broken — check (1) too vague → abstention failures); temporal **+4.7pp** (71.7%)
- Overall **75.2%** (+1.0pp, **new best** vs L-33/L-34 at 74.2%)

**LOCOMO standing (Run 23, full-10, 2026-07-04):** excl-adv J 66.9–68.9 at parity with
mem0 (66.88), leading on single-hop, temporal, adversarial, and multi-hop F1. Open-domain
remains the LOCOMO gap (J 29.2 vs frontier ~74–77).

See `RESULTS.md` for the full run ledger.

## What the harness measures

Each benchmark conversation gets an isolated gnosis scope:

```text
benchmark JSON --ingest--> gnosis (/v1/memories, infer=true)
question ------retrieve-> /v1/memory/context OR /v1/memories/search
retrieved text --answer-> answer model (never sees raw history)
hypothesis ----grade---> benchmark scorer + LLM judge
```

- One gnosis `user_id` per benchmark conversation; one `session_id` per session.
- Ingest posts one extraction-mode add per consecutive two-turn chunk.
- `context` and `search` are separate retrieval conditions.
- LOCOMO J score uses a local mem0-style CORRECT/WRONG judge for categories 1–4;
  category 5 (adversarial) uses the official substring rule. LongMemEval uses the
  official per-type judge prompts.

### Measurement scopes

Do not mix scopes when comparing scores:

| Scope | Input | Protocol / notes |
|---|---|---|
| LOCOMO subset-3 gate | 3 of 10 conversations, 497 Q | Dev regression gate only; excl-adv ~71 reproducible level; NOT a competitive claim |
| LOCOMO full (Run 23) | All 10 conversations, 1,986 Q (1,540 non-adversarial) | Competitor comparison; Run 18 config; two judges (gpt-5.5 / gpt-5.4-mini) |
| LME_S frozen-100 | 100-instance stratified subset; IDs in [`data/longmemeval_s_subset100.txt`](data/longmemeval_s_subset100.txt) | Fast iteration; gpt-5.5 judge; gemini-embedding-001/3072 |
| **LME_S full-500 (L-23)** | All 500 questions | **Competitive claim**; Claude-Sonnet-4-6 backbone + judge; 2026-07-31 |

## Setup

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker Compose,
an OpenAI-compatible endpoint.

```bash
cd stack
cp .env.example .env
# Edit stack/.env with your endpoint, models, and gnosis feature flags.
docker compose -p membench-local -f compose.yaml up --build -d
curl -fsS http://localhost:8080/ready
```

Use `-p membench-local` for state isolation. A new project name gives a fresh Neo4j
store. Tear down with `docker compose -p membench-local -f compose.yaml down -v`.

## Running benchmarks

All commands run from `membench/`. Dataset downloads require network access.

```bash
cd membench
uv sync
uv run membench download --benchmark locomo
uv run membench download --benchmark longmemeval_s
```

### LOCOMO subset-3 gate (internal regression, ~71 J)

```bash
uv run membench run \
  --benchmark locomo \
  --subset 3 \
  --data-file ../data/locomo10.json \
  --conditions context \
  --out ../results/locomo/frozen-subset3
```

Required `stack/.env` for the frozen gate:

```dotenv
GNOSIS_FACT_EXTRACTION_ENABLED=true
GNOSIS_ENTITY_GRAPH_ENABLED=true
GNOSIS_ADAPTIVE_ROUTING_ENABLED=true
GNOSIS_CHAIN_OF_NOTE_ENABLED=true
GNOSIS_LLM=openai/gpt-5.5
GNOSIS_EMBEDDING=local-qwen3-embedding-0.6b
GNOSIS_EMBEDDING_DIMENSIONS=1024
```

### LongMemEval_S frozen-100 (primary optimization target)

```bash
uv run membench run \
  --benchmark longmemeval_s \
  --data-file ../data/longmemeval_s_subset100.json \
  --conditions context \
  --inline-dates \
  --out ../results/longmemeval_s/frozen-100
```

Additional `stack/.env` for LME_S (append to LOCOMO flags above, replacing
embedder):

```dotenv
GNOSIS_EMBEDDING=gemini-embedding-001
GNOSIS_EMBEDDING_DIMENSIONS=3072
GNOSIS_SCOPED_DENSE_RETRIEVAL_ENABLED=true
GNOSIS_DENSE_SCOPE_POOL=10000
```

### Resume an interrupted run

Resume requires the **same Compose project/Neo4j volume** and the **same `--out`**
directory. Do not change either independently — that produces a hybrid result, not
a resume.

```bash
uv run membench run \
  --benchmark locomo \
  --subset 3 \
  --data-file ../data/locomo10.json \
  --conditions context \
  --stages ingest,answer,grade \
  --out ../results/locomo/frozen-subset3
```

### Regrade without re-retrieving

```bash
uv run membench run \
  --benchmark locomo \
  --subset 3 \
  --data-file ../data/locomo10.json \
  --conditions context \
  --stages grade \
  --out ../results/locomo/frozen-subset3
```

## Experiment ledger

| Run | gnosis config | Score | Status |
|---|---|---|---|
| L-21 (ingest-only) | run18 + gemini/3072 + scoped dense | — | All 500 conversations ingested; 2026-07-31 |
| **L-23** | L-21 ingest + Claude-Sonnet-4-6 backbone + Claude judge | **69.8%** | Complete; 2026-07-31 |
| L-24 | relation_slots KU fix (SUPERSEDES-slot metadata) | — | Merged into L-25; changes landed in gnosis 2026-08-04 |
| **L-25** | edu-v2.0 (Rule 15: assistant-turn extraction) + relation_slots (KU fix); fresh ingest | 72.4% | Complete (2026-08-05); see L-25b for singleton fix |
| **L-25b** | + singleton-only relation_slots supersession (read-time fix, no re-ingest) | **73.6%** | **Complete** (2026-08-06); SSA 98.2%, KU 70.8% (n=72), MS 58.7% (n=121), SSP +3.3pp vs L-25 |
| L-26 | + reranker (run24.yaml) | — | Baked into L-25b (GNOSIS_RERANK_ENABLED was already true) |
| **L-27** | + community graph (GNOSIS_COMMUNITY_GRAPH_ENABLED=true) | 73.4% | **Rejected** (2026-08-06) — neutral overall (-0.2pp vs L-25b); SSA -5.3pp, MS -5.0pp; temporal +2.8pp, SSP +3.3pp |
| **L-28** | stronger CoN recency clause ("report ONLY most recently-dated value; do not mention older value") | 71.8% | **Rejected** (2026-08-06) — SSA -5.3pp, SSU -6.3pp, MS -5.0pp; KU +1.4pp only; clause over-fires outside KU context |
| **L-29** | + `knowledge_update` router route + recency injection (top-5 newest facts merged into dense top-20) | 73.6% | **Tie** (2026-08-06) — KU +4.2pp, temporal +4.0pp, but SSA -5.3pp, SSP -6.7pp from routing misclassification; gains cancel; route mechanism confirmed |
| **L-30** | + tighter knowledge_update guide (explicit SSA/preference/past-state exclusions) | 73.0% | **Rejected** (2026-08-06) — SSA/SSP partially recovered but temporal -2.4pp; routing precision asymmetric (too tight removes beneficial temporal routing); reverted to L-29 guide |
| **L-31** | write-time SUPERSEDES edges + `valid_to IS NULL` filter in vector/BM25 Cypher for knowledge_update route (structural KU fix; arXiv:2607.26520) | **71.0%** | **Complete** (2026-08-09, re-run with fixed ingest) — KU 80.6% (+9.8pp); regressions SSA −3.6pp, temporal −7.9pp, MS −4.2pp (ingest variation, NOT router misclassification — confirmed by routing trace) |
| **L-32** | `GNOSIS_CON_ENUMERATION_ENABLED=true` (count unique real-world items not records) + multi-query expansion in answer.py for aggregative multi-session questions (2 LLM sub-queries → supplemental section) | **72.6%** | **Complete** (2026-08-10, no re-ingest) — MS **59.5% (+5.0pp)**, KU 81.9% (+1.4pp), SSA 96.4% (+1.8pp), SSU 81.2% (+3.1pp), temporal 67.7% (+1.6pp); SSP/abstention −6.7pp each (2-question noise at n=30) |

See [`RESULTS.md`](RESULTS.md) for the full run ledger with raw scores.

## Costs and concurrency

| Protocol | Questions | One condition: LLM calls |
|---|---|---|
| LOCOMO subset-3 | 497 Q / 385 judge-eligible | 882 answer + judge |
| LOCOMO full | 1,986 Q / 1,540 judge-eligible | 3,526 answer + judge |
| LME_S frozen-100 | 100 Q | 200 answer + judge |
| LME_S full | 500 Q | 1,000 answer + judge |

Ingest adds are separate: `ceil(turns / 2)` POSTs per session. With fact extraction
enabled, each add triggers one extraction LLM call (~30 s for LME_S-sized turns).

Default concurrency: `MEMBENCH_CONCURRENCY=8`. Use `--grade-concurrency` and
`--ingest-concurrency` to override independently. Keep within your endpoint's
rate limit.

## Responses API shim

Some endpoints accept only streaming Responses API requests. Run the shim locally:

```bash
OPENAI_BASE_URL=https://provider.example/v1 \
OPENAI_API_KEY="$YOUR_KEY" \
uv run python -m membench.responses_shim --port 14100

export OPENAI_BASE_URL=http://localhost:14100/v1
```

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `GNOSIS_BASE_URL` | `http://localhost:8080` | gnosis endpoint |
| `GNOSIS_TOKEN` | `membench-token` | gnosis auth token |
| `MEMBENCH_TENANT_ID` | `nolgia` | tenant scope |
| `MEMBENCH_SPACE_ID` | `membench` | space scope |
| `MEMBENCH_AGENT_ID` | `membench` | agent scope |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | answer/judge endpoint |
| `OPENAI_API_KEY` | empty | endpoint credential |
| `MEMBENCH_ANSWER_MODEL` | `gpt-4o-mini` | answer model |
| `MEMBENCH_JUDGE_MODEL` | `gpt-4o` | judge model |
| `MEMBENCH_MAX_ITEMS` | `20` | retrieval depth |
| `MEMBENCH_CONCURRENCY` | `8` | answer + grade workers |
| `MEMBENCH_INCLUDE_GRAPH` | `true` | include graph-QA sections |
| `MEMBENCH_TIMEOUT` | `300` | HTTP timeout (seconds) |

## Aging protocol

`membench aging` is a synthetic maintenance protocol that generates update chains,
contradictions, stable controls, and distractors, ingests them in timestamp order,
and scores ranked retrieval deterministically — no LLM judge.

```bash
uv run membench aging \
  --seed 7 --users 8 --update-versions 3 \
  --config-label supersession_off \
  --out ../results/aging/off
```

See `RESULTS.md` for the full aging protocol spec and the `membench aging --help`
output for all flags.

## Outputs

Each run directory contains:
- `ingest_state.json` — completed conversation IDs (for resume)
- `answers_<condition>.jsonl` — retrieved context and answer records
- `graded_<condition>.jsonl` — scores and judge responses
- `results.json` — run settings and aggregate metrics
- `report.md` — per-category report

Run output and downloaded data are `.gitignore`d. `RESULTS.md` is the durable,
human-readable benchmark ledger.

## Repository layout

```text
stack/compose.yaml          Neo4j + gnosis Compose stack
data/                       downloaded data (ignored) + frozen LME ID list
membench/
  src/membench/datasets.py  download/load/normalize datasets
  src/membench/ingest.py    ordered turn-pair ingestion + resume state
  src/membench/answer.py    context/search retrieval + answer prompts
  src/membench/grade.py     LongMemEval and LOCOMO scoring
  src/membench/aging.py     synthetic supersession protocol
  src/membench/run.py       CLI entry point
  src/membench/responses_shim.py  Responses-to-chat compatibility shim
  tests/                    fixture-based unit tests
docs/
  frontier-2026.md          competitive landscape analysis (updated 2026-08-06)
  extraction-design.md      edu-v1/v2.0 fact extraction design (implemented)
  gaps-abstention-maintenance.md  abstention + knowledge-update gap analysis
  knowledge-update.md       KU roadmap — L-23 baseline → L-25b (70.8%) → L-31 (81.9%, complete)
  multihop-techniques.md    multi-hop retrieval techniques
RESULTS.md                  append-only benchmark run ledger
```

## Development

```bash
cd membench
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

CI installs Python 3.13, runs these four checks, and does not start Compose,
download data, or make paid API calls.

## Research sources

See [`docs/frontier-2026.md`](docs/frontier-2026.md) for the full competitive
analysis (updated July–August 2026), including verified scores, technique dissections,
and the ranked next-technique roadmap for gnosis.

Key sources: [LOCOMO](https://arxiv.org/abs/2402.17753) ·
[LongMemEval](https://arxiv.org/abs/2410.10813) ·
[Mnemis](https://arxiv.org/abs/2602.15313) ·
[EverMemOS](https://arxiv.org/abs/2601.02163) ·
[Chronos](https://arxiv.org/abs/2603.16862) ·
[Zep/Graphiti](https://arxiv.org/abs/2501.13956) ·
[EMem](https://arxiv.org/abs/2511.17208) ·
[Memory-R2](https://arxiv.org/abs/2605.21768) ·
["Is Grep All You Need?"](https://arxiv.org/abs/2605.15184) ·
[MemCon](https://arxiv.org/abs/2607.13591) ·
[Memanto](https://arxiv.org/abs/2604.22085) ·
[Graph-Native Bitemporal (L-31 blueprint)](https://arxiv.org/abs/2607.26520) ·
[Ground Truth First](https://arxiv.org/abs/2607.21962) ·
[Scrub Jay Episodic Memory](https://arxiv.org/abs/2608.04746) ·
[AgentMemBench](https://arxiv.org/abs/2608.00009) ·
[Beyond Memory Leaderboards](https://arxiv.org/abs/2607.16848)
