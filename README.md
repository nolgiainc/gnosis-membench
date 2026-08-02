# gnosis-membench

Benchmark harness for the [gnosis memory service](https://github.com/nolgiainc/gnosis).
Runs LongMemEval_S and LOCOMO through a consistent ingest → retrieval → answer →
grade pipeline. Results are logged in [`RESULTS.md`](RESULTS.md), the append-only
run ledger.

**Current standing — LongMemEval_S L-23 (full 500-Q, 2026-07-31):**
Claude-Sonnet-4-6 backbone + Claude judge via gnosis context retrieval.

| Category | L-23 | Notes |
|---|---|---|
| abstention | 100.0% (n=30) | Perfect recall of unanswerable questions |
| single-session-preference | 96.7% (n=30) | Strong personalization recall |
| single-session-user | 87.5% (n=64) | Strong user-stated fact recall |
| temporal-reasoning | 82.7% (n=127) | Solid; Chronos SOTA 95.5% |
| multi-session | 73.6% (n=121) | Competitive; Chronos SOTA 88.7% |
| single-session-assistant | 41.1% (n=56) | Gap: assistant-stated facts under-indexed |
| knowledge-update | 23.6% (n=72) | **Primary gap** — stale facts returned; Zep 83.3% |
| **Overall** | **69.8%** (500 Q) | vs Zep 71.2%, mem0 67.6%, Chronos 95.6% |

**Primary optimization targets:**
1. **Knowledge-update (23.6%)** — SUPERSEDES edges + event calendar. See [`docs/knowledge-update.md`](docs/knowledge-update.md).
2. **Single-session-assistant (41.1%)** — edu-v1 extractor misses assistant-stated commitments; needs extractor prompt update.

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
| L-24 | + SUPERSEDES edges + event calendar (KU fix) | — | Queued — primary KU gap target |
| L-25 | + SSA extractor update (assistant-stated facts) | — | Queued — secondary gap |
| L-26 | + reranker (run24.yaml) | — | Queued — retrieval bottleneck |
| L-27 | + community graph + multi-query rewrite (run25.yaml) | — | Queued — open-domain + multi-hop |

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
  frontier-2026.md          competitive landscape analysis (updated 2026-07-17)
  extraction-design.md      edu-v1 fact extraction design
  gaps-abstention-maintenance.md  abstention + knowledge-update gap analysis
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
analysis (updated July 2026), including verified scores, technique dissections,
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
[MemCon](https://arxiv.org/abs/2607.13591)
