# AGENTS.md — gnosis-membench benchmark harness

This repo benchmarks the [gnosis](https://github.com/nolgiainc/gnosis) long-term
memory service on LongMemEval_S (primary) and LOCOMO. It runs an
ingest → retrieve → answer → grade pipeline against a live gnosis instance.

---

## Quick orientation

```
stack/compose.yaml          Neo4j + gnosis Docker stack
data/                       downloaded datasets (gitignored)
membench/                   Python benchmark harness (uv)
  src/membench/run.py       CLI entry point
  src/membench/ingest.py    session ingestion
  src/membench/answer.py    retrieval + answer generation
  src/membench/grade.py     LME_S and LOCOMO scoring
results/                    run outputs (gitignored)
RESULTS.md                  durable benchmark ledger
docs/frontier-2026.md       competitive analysis
```

---

## Prerequisites

- Docker + Compose (for the Neo4j + gnosis stack)
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) in the environment
- `GNOSIS_CONTEXT` pointing at a gnosis repo checkout (defaults to `../../gnosis`)

---

## Starting the stack

```bash
cd stack
cp .env.example .env          # edit with API keys and model names
docker compose -p membench-lme -f compose.yaml up --build -d
curl -fsS http://localhost:8080/ready   # wait until 200 OK
```

Use `-p membench-lme` for state isolation. Each project name gets its own
Neo4j volume. Tear down (and wipe data) with:
```bash
docker compose -p membench-lme -f compose.yaml down -v
```

---

## Running benchmarks

All commands from `membench/`:

```bash
cd membench
uv sync
```

### Download data (run once)

```bash
uv run membench download --benchmark longmemeval_s
uv run membench download --benchmark locomo
```

### LME_S frozen-100 (primary optimization loop, ~30 min)

```bash
uv run membench run \
  --benchmark longmemeval_s \
  --data-file ../data/longmemeval_s_subset100.json \
  --conditions context \
  --inline-dates \
  --out ../results/longmemeval_s/frozen-100
```

Required stack `.env` additions for LME_S:
```dotenv
GNOSIS_EMBEDDING=openai/azure/openai/text-embedding-3-large
GNOSIS_EMBEDDING_DIMENSIONS=3072
GNOSIS_SCOPED_DENSE_RETRIEVAL_ENABLED=true
GNOSIS_DENSE_SCOPE_POOL=10000
```

### LOCOMO subset-3 regression gate (~71 J, ~15 min)

```bash
uv run membench run \
  --benchmark locomo \
  --subset 3 \
  --data-file ../data/locomo10.json \
  --conditions context \
  --out ../results/locomo/frozen-subset3
```

### Resume an interrupted run

Pass `--stages answer,grade` (or `grade` alone) to skip already-completed stages.
The `ingest_state.json` in `--out` tracks completed session IDs.

```bash
uv run membench run \
  --benchmark longmemeval_s \
  --data-file ../data/longmemeval_s_subset100.json \
  --conditions context \
  --inline-dates \
  --stages answer,grade \
  --out ../results/longmemeval_s/frozen-100
```

---

## NVIDIA inference gateway (primary endpoint)

All models route through `https://inference-api.nvidia.com/v1` — an OpenAI-compatible
LiteLLM proxy covering 224 models across AWS Bedrock, GCP Vertex, Azure OpenAI,
OpenAI direct, and NVIDIA NIM. Auth: `Authorization: Bearer $INFERENCE_API_KEY`
(set in `~/.dotfiles/zsh/.config/zsh/zsh-secrets`).

**Tested model selections (2026-07-17):**

| Role | Model | Notes |
|---|---|---|
| gnosis LLM | `openai/azure/openai/gpt-4o-mini` | extraction, routing, CoN — verified working 2026-07-17 |
| gnosis embed | `openai/azure/openai/text-embedding-3-large` | 3072 dims — verified working 2026-07-17; `openai/` prefix routes via OPENAI_BASE_URL |
| embed alt | `openai/azure/openai/text-embedding-3-large` | 3072 dims, matches LME_S frozen config |
| reader (competitive) | `azure/openai/gpt-4o` | comparable to published LME_S baselines — verified 2026-07-17 |
| reader (fast iter) | `azure/openai/gpt-4o-mini` | cheap reader for iteration |
| reader (Claude) | `aws/anthropic/claude-haiku-4-5-v1` | fast, via AWS Bedrock |
| judge | `azure/openai/gpt-4o` | stable, comparable to leaderboard — verified 2026-07-17 |
| judge (alt) | `aws/anthropic/claude-haiku-4-5-v1` | Claude-native judging — verified 2026-07-17 |
| community/rewrite LLM | `nvidia/qwen/qwen3-32b` | on-prem NVIDIA, no egress cost |

Quick environment setup for a benchmark run:
```bash
source ~/.dotfiles/zsh/.config/zsh/zsh-secrets
export OPENAI_BASE_URL=https://inference-api.nvidia.com/v1
export OPENAI_API_KEY=$INFERENCE_API_KEY
export MEMBENCH_ANSWER_MODEL=azure/openai/gpt-4o
export MEMBENCH_JUDGE_MODEL=azure/openai/gpt-4o
```

---

## Model configuration

Set via environment variables (or `stack/.env` for gnosis internals):

| Variable | Default | Notes |
|---|---|---|
| `MEMBENCH_ANSWER_MODEL` | `gpt-4o-mini` | reader model — what answers from retrieved context |
| `MEMBENCH_JUDGE_MODEL` | `gpt-4o` | judge model — grades whether the answer is correct |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | — | key for the answer/judge endpoint |
| `MEMBENCH_CONCURRENCY` | `8` | parallel answer+grade workers |
| `MEMBENCH_MAX_ITEMS` | `20` | retrieval depth |

### Use codex-mini as the reader

Fast and cheap for internal iteration; not comparable to gpt-4o-mini published results.

```bash
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_API_KEY="$OPENAI_API_KEY"
export MEMBENCH_ANSWER_MODEL=codex-mini-latest
export MEMBENCH_JUDGE_MODEL=gpt-4o   # keep judge stable for comparability
```

### Use Claude as the reader (via Anthropic's OpenAI-compatible endpoint)

```bash
export OPENAI_BASE_URL=https://api.anthropic.com/v1
export OPENAI_API_KEY="$ANTHROPIC_API_KEY"
export MEMBENCH_ANSWER_MODEL=claude-haiku-4-5-20251001   # fast + cheap
export MEMBENCH_JUDGE_MODEL=claude-sonnet-5              # or keep gpt-4o with a second key
```

**Note:** LME_S judge scores depend heavily on the judge model. For competitive
comparison use the same judge model (gpt-4o or gpt-5.5) as published leaderboard
entries. Changing the judge model shifts all scores; always log it in RESULTS.md.

### LiteLLM proxy (route both OpenAI and Anthropic through one endpoint)

```bash
export OPENAI_BASE_URL=http://localhost:4000/v1
export OPENAI_API_KEY=sk-litellm
export MEMBENCH_ANSWER_MODEL=claude-haiku-4-5-20251001
export MEMBENCH_JUDGE_MODEL=gpt-4o
```

---

## Checking results

After a run completes, `results/` holds:

```
results/longmemeval_s/frozen-100/
  report.md             # per-type accuracy table
  results.json          # aggregate scores + run config
  graded_context.jsonl  # per-question scores
  answers_context.jsonl # retrieved context + answer text
  ingest_state.json     # completed session IDs (for resume)
```

Key score: `lme_overall_accuracy` (and per-type: `knowledge_update`, `multi_session`,
`temporal_reasoning`, `single_session_user`, `abstention`).

---

## Common tasks for an agent

**Start a fresh LME_S run:**
1. `cd stack && docker compose -p membench-lme up --build -d`
2. `curl -fsS http://localhost:8080/ready` until 200
3. `cd membench && uv run membench download --benchmark longmemeval_s` (if data missing)
4. Run the LME_S frozen-100 command above
5. `cat ../results/longmemeval_s/frozen-100/report.md`

**Tear down after a run:**
`cd stack && docker compose -p membench-lme down -v`

**Run the quick regression gate (subset-3, no data download needed after first run):**
`cd membench && uv run membench run --benchmark locomo --subset 3 --data-file ../data/locomo10.json --conditions context --out ../results/locomo/frozen-subset3`

**Regrade without re-retrieving:**
`uv run membench run --benchmark longmemeval_s --data-file ../data/longmemeval_s_subset100.json --conditions context --inline-dates --stages grade --out ../results/longmemeval_s/frozen-100`

**Run linting / tests:**
```bash
cd membench
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

---

## Writing results to RESULTS.md

After each notable run, append a row to the appropriate table in `RESULTS.md` with:
- Run ID (L-N for LME_S, R-N for LOCOMO)
- Date
- Config (gnosis feature flags)
- Reader model
- Judge model
- Overall accuracy / J score
- Per-type breakdown if noteworthy

Then commit: `git commit -m "results: LME_S L-N <score> (<reader> reader, <judge> judge)"`
