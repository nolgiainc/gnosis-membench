# gnosis-membench

`gnosis-membench` is a benchmark harness for the [gnosis memory
service](https://github.com/nolgiainc/gnosis). It runs LongMemEval_S and LOCOMO
through the same ingest, retrieval, answer, and grading pipeline. The harness
is **protocol-aligned**, not universally directly comparable to every published
number: dataset size, judge model, answer model, embeddings, write/read flags,
and provider behavior must match before scores can be compared.

`RESULTS.md` is the detailed, append-only run ledger. It records the frozen
configs, deviations, category tables, and provenance that are too detailed for
this quickstart.

## What the harness measures

Each benchmark conversation gets an isolated gnosis scope:

```text
benchmark JSON --ingest--> gnosis (/v1/memories, infer=true)
question ------retrieve-> /v1/memory/context OR /v1/memories/search
retrieved text --answer-> answer model (never sees raw history)
hypothesis ----grade---> benchmark scorer and, where applicable, an LLM judge
```

- One gnosis `user_id` is used per benchmark conversation and one `session_id`
  per benchmark session.
- Ingest posts one extraction-mode add for each consecutive two-turn chunk
  (normally a user+assistant **turn-pair**; roles are preserved as present,
  and an odd final turn is sent alone). A session with `T` retained turns
  therefore has `ceil(T / 2)` add requests. Pairing is per session; do not
  calculate one `ceil(total_turns / 2)` across all sessions.
- Session dates are sent as add `metadata.session_date`. `--inline-dates` is an
  optional compatibility switch that also prefixes the turn text; it changes
  the benchmark input and is off by default.
- `context` and `search` are separate retrieval conditions. The answerer sees
  only the retrieved text. LongMemEval judge prompts and LOCOMO lexical rules
  follow their source implementations; LOCOMO's `J` score is a local
  mem0-style CORRECT/WRONG judge for categories 1–4, while category 5 uses the
  deterministic substring rule. These and the model/provider deviations below
  are intentional and recorded in `RESULTS.md`.

### Measurement scopes

Do not mix these scopes when interpreting a score:

| Scope | Input and purpose | Frozen details |
| --- | --- | --- |
| LOCOMO subset-3 gate | 3 of 10 conversations, 497 questions; fast internal regression signal | Run 18 write/read configuration, qwen3 1024-dim embeddings, gpt-5.5 answerer/judge via the Responses shim, context condition; reproducible level is about 71 J excluding adversarial |
| LOCOMO full Run 23 | All 10 conversations, 1,986 questions (1,540 non-adversarial); competitor comparison | Same Run 18 configuration; gpt-5.5 and gpt-5.4-mini judges; gpt-4o-mini was not routable on the self-hosted stack |
| LongMemEval_S frozen subset | 100 question instances from the 500-question dataset, including all 30 abstention instances; primary optimization target | IDs in [`data/longmemeval_s_subset100.txt`](data/longmemeval_s_subset100.txt), gpt-5.5 judge, gemini-embedding-001 at 3072 dimensions, scoped dense retrieval, and `--inline-dates` |

The subset-3 score is a development gate, not a full-LOCOMO competitive claim.
Run 23's verified headline is **66.9 J (gpt-5.5) / 68.9 J
(gpt-5.4-mini), excluding adversarial**, versus mem0 66.88 and the published
full-context ceiling 72.90. That is parity with mem0, not a claim of leading the
field. Run 23's defensible full-n signals are single-hop (F1 and J), temporal J,
adversarial J, and multi-hop F1; open-domain is the clear weakness. See the
[Run 23 ledger](RESULTS.md) for category values and judge sensitivity.

## Prerequisites and local stack

- Python **3.12 or newer**. CI currently installs Python 3.13.
- [uv](https://docs.astral.sh/uv/) for the project environment.
- Docker Compose for a local Neo4j + gnosis stack.
- An OpenAI-compatible endpoint for gnosis extraction/embeddings and for the
  answerer/judge. Hosted endpoints can incur charges; fixture tests and config
  validation do not contact a live service.

The Compose file builds gnosis from a sibling checkout by default. Set
`GNOSIS_CONTEXT` in `stack/.env` if your checkout is elsewhere.

```bash
cd stack
cp .env.example .env
# Edit stack/.env for the endpoint and models you intend to use.
docker compose -p membench-local -f compose.yaml up --build -d
curl -fsS http://localhost:8080/ready
```

The `-p` project name is part of state isolation. Compose's `neo4j-data`
named volume is scoped to that project, so a new project name gives a fresh
store. Reusing the same project reuses its volume. To destroy a disposable
store explicitly:

> **Local-only warning:** the default Compose port mappings bind Neo4j and
> gnosis on the host's network interfaces, and the default auth values are
> placeholders. Never expose this stack on a shared, public, or production
> network. For local use, bind the host side of both ports to `localhost` with a
> Compose override (or use an isolated container context), and replace the
> `membench-token`, Neo4j password, and operator-token defaults before any
> non-disposable run.

```bash
docker compose -p membench-local -f compose.yaml down -v
```

`down -v` deletes the named volume. A new `--out` directory does **not** reset
Neo4j and must not be mistaken for a fresh benchmark store.

Stop a stack without deleting its volume with:

```bash
docker compose -p membench-local -f compose.yaml down
```

## Install, inspect, and download data

From `membench/`, the following commands are local and do not contact gnosis:

```bash
cd membench
uv sync
uv run membench --help
uv run membench run --help
uv run membench aging --help
```

`membench` reads its configuration from the process environment; it does not
load `stack/.env`. Export the harness-side endpoint, key, models, and flags in
the shell that runs `uv run membench` (the defaults are listed below).

Dataset downloads are network operations. The files live under the ignored
repository-root `data/` directory; pass `--data-file` when you need to pin a
particular file path.

```bash
uv run membench download --benchmark locomo
uv run membench download --benchmark longmemeval_s
```

The frozen LongMemEval subset list is tracked, but the JSON data files are not.
After downloading `longmemeval_s_cleaned.json`, regenerate the subset JSON from
the tracked IDs when needed:

```bash
uv run python scripts/make_lme_subset100.py
```

The input files, run outputs, gnosis image/commit, Compose environment, and
provider responses are mutable machine state. `results.json` records selected
run settings but does not hash or freeze all of that state. For a reproducible
claim, preserve the input checksum, exact `--data-file`, gnosis revision/image,
Compose environment, model routes, and run output together; a path alone is not
provenance.

## Run commands and resume semantics

All examples below run from `membench/`. Live ingest, answer, and aging examples
require a ready gnosis stack and an endpoint. Grade-only regrade requires the
existing answer JSONL plus a judge endpoint, but does not contact gnosis. These
are cost-bearing live examples, not part of the local documentation QA.

### A small live smoke run

Use a disposable Compose project and an explicit output directory. `--subset 1`
limits LOCOMO to one conversation; it does not make the run free.

```bash
uv run membench run \
  --benchmark locomo \
  --subset 1 \
  --data-file ../data/locomo10.json \
  --conditions context,search \
  --out ../results/locomo/smoke-1
```

### Frozen LOCOMO subset-3 gate

The gate is the internal regression protocol. Its exact gnosis feature flags,
models, and judge caveats are in `RESULTS.md`; the command fixes the dataset,
condition, and output path:

```bash
uv run membench run \
  --benchmark locomo \
  --subset 3 \
  --data-file ../data/locomo10.json \
  --conditions context \
  --out ../results/locomo/frozen-subset3
```

Use a new Compose project (or delete a disposable volume) before a fresh
ingest, and set the Run 18 flags/models in `stack/.env` before recreating the
stack:

```dotenv
# LOCOMO Run 18 write/read flags (all four are required; Compose defaults are off)
GNOSIS_FACT_EXTRACTION_ENABLED=true
GNOSIS_ENTITY_GRAPH_ENABLED=true
GNOSIS_ADAPTIVE_ROUTING_ENABLED=true
GNOSIS_CHAIN_OF_NOTE_ENABLED=true
GNOSIS_LLM=openai/gpt-5.5
GNOSIS_EMBEDDING=local-qwen3-embedding-0.6b
GNOSIS_EMBEDDING_DIMENSIONS=1024
```

From `membench/`, recreate the disposable gate stack after editing
`stack/.env`:

```bash
docker compose -p membench-locomo -f ../stack/compose.yaml up --build -d
```

Export the answer/judge endpoint and models in the `membench/` shell as well;
`stack/.env` is read by Compose, not by `membench`:

```bash
export OPENAI_BASE_URL=http://localhost:14100/v1  # or your LiteLLM endpoint
export OPENAI_API_KEY="$YOUR_KEY"
export MEMBENCH_ANSWER_MODEL=gpt-5.5
export MEMBENCH_JUDGE_MODEL=gpt-5.5
export MEMBENCH_INCLUDE_GRAPH=false
```

Use a container-reachable `OPENAI_BASE_URL` in `stack/.env`; the shell export
may instead point at the local Responses shim when only the harness needs that
compatibility route.

The gate's historical 74.8 score is retained in `RESULTS.md`; the
reproducible level is approximately 71 and is not a full-n competitor result.

### Frozen LongMemEval_S 100-instance run

This is the primary optimization protocol, not a published full-500 result:

```bash
uv run membench run \
  --benchmark longmemeval_s \
  --data-file ../data/longmemeval_s_subset100.json \
  --conditions context \
  --inline-dates \
  --out ../results/longmemeval_s/frozen-100
```

The frozen configuration uses the tracked ID list, scoped dense retrieval, the
LongMemEval-specific embedding setup, and the judge/model settings documented in
`RESULTS.md`. Before recreating the stack, use these additional `stack/.env`
values instead of the LOCOMO embedding/scope values above:

```dotenv
GNOSIS_EMBEDDING=gemini-embedding-001
GNOSIS_EMBEDDING_DIMENSIONS=3072
GNOSIS_SCOPED_DENSE_RETRIEVAL_ENABLED=true
GNOSIS_DENSE_SCOPE_POOL=10000
```

Keep the four Run 18 feature flags and `GNOSIS_LLM` from the LOCOMO block,
export the same answer/judge variables, and use a fresh Compose project. Do not
describe a subset run as the full benchmark.

```bash
docker compose -p membench-lme100 -f ../stack/compose.yaml up --build -d
```

### Resume an interrupted run

Resume means reusing **both** the same Compose project/Neo4j volume and the same
`--out` directory. Ingest records completed conversation IDs in
`ingest_state.json`; answer and grade records stream to per-condition JSONL and
skip IDs already present. Keep the original data file and relevant flags:

```bash
uv run membench run \
  --benchmark locomo \
  --subset 1 \
  --data-file ../data/locomo10.json \
  --conditions context,search \
  --stages ingest,answer,grade \
  --out ../results/locomo/smoke-1
```

Using a different `--out` starts new output/state files. Using a different
Compose project starts a new store; that is a fresh run, not a resume.
For a genuinely fresh store, change **both** the Compose project/volume and
`--out`. Reusing an old `--out` with a new project reuses `ingest_state.json`,
so completed conversation IDs are skipped and the new store can remain empty.

### Regrade existing answers

`--stages grade` reads the existing `answers_<condition>.jsonl` files and writes
graded JSONL, `results.json`, and `report.md`. It does not retrieve from gnosis,
but it still requires the original `--out` and answer records:

```bash
uv run membench run \
  --benchmark locomo \
  --subset 3 \
  --data-file ../data/locomo10.json \
  --conditions context \
  --stages grade \
  --out ../results/locomo/frozen-subset3
```

On a fresh output directory, regrade fails closed with
`error: no answers for condition 'context'`; it does not contact a live
service. A different dataset or condition can make an old answer file
misleading, so keep the original command metadata with the output.

## Calls, costs, and concurrency

The counts below are derived from the current harness. They count retrieval
HTTP requests and answer/judge LLM calls; they exclude gnosis's ingest-side
extraction calls, feature-enabled read-side calls (for example adaptive
routing, graph QA, or recall filters), and provider retries.

| Protocol | Questions `Q` | Judge-eligible `J` | One retrieval condition | Two retrieval conditions |
| --- | ---: | ---: | --- | --- |
| LOCOMO subset-3 gate | 497 | 385 (`497 - 112` adversarial) | 497 retrieval HTTP requests; 497 answer + 385 judge = **882** answer/judge LLM calls | 994 retrieval HTTP requests; 994 answer + 770 judge = **1,764** answer/judge LLM calls |
| LOCOMO full Run 23 | 1,986 | 1,540 (`1,986 - 446` adversarial) | 1,986 retrieval HTTP requests; 1,986 answer + 1,540 judge = **3,526** answer/judge LLM calls | 3,972 retrieval HTTP requests; 3,972 answer + 3,080 judge = **7,052** answer/judge LLM calls |
| LongMemEval_S frozen subset-100 | 100 | 100 (including abstention questions) | 100 retrieval HTTP requests; 100 answer + 100 judge = **200** answer/judge LLM calls | 200 retrieval HTTP requests; 200 answer + 200 judge = **400** answer/judge LLM calls |
| LongMemEval_S full dataset (not a frozen run) | 500 | 500 | 500 retrieval HTTP requests; 500 answer + 500 judge = **1,000** answer/judge LLM calls | 1,000 retrieval HTTP requests; 1,000 answer + 1,000 judge = **2,000** answer/judge LLM calls |

LOCOMO category 5 (adversarial) uses the official deterministic
`no information available`/`not mentioned` substring rule, so it has no judge
call. LongMemEval abstention questions still receive the official judge prompt.
For reference, a two-condition full-LOCOMO plus full-LongMemEval campaign is
**9,052** answer/judge LLM calls; frozen LME-100 plus full LOCOMO is **7,452**.
Those totals are accounting formulas, not a recommendation to launch a paid
full benchmark.

Ingest adds are separate from the table: each session contributes
`ceil(turns_in_session / 2)` POSTs. If gnosis fact extraction is enabled, those
logical adds normally trigger one extraction request each; malformed responses
can be retried, so provider-attempt counts can be higher. With extraction off,
gnosis stores the add without an extraction LLM call.
For the audited inputs, logical add counts are 742 for LOCOMO subset-3, 3,011
for full LOCOMO, and 24,910 for frozen LME-100. They are input-specific: a
changed data file changes the add count even when `Q` stays the same.

The default `MEMBENCH_CONCURRENCY=8` controls answer and grade workers.
`--concurrency 1` is useful for serial debugging; `--grade-concurrency N`
overrides only grade workers, and `--ingest-concurrency N` pools sessions across
all conversations while preserving add order within each session. Keep workers
within the endpoint's rate limit: concurrency changes throughput and retry
behavior, not the logical call counts above.

### Responses API shim

Some ChatGPT/Codex routes accept only streaming Responses API requests. The
local shim forwards a minimal chat-completions request to `/v1/responses`,
aggregates the SSE stream, and returns normal chat-completion JSON. It drops
unsupported `temperature`/`max_tokens` parameters, so a provider's default
temperature is part of the documented deviation. It expects the configured
upstream route to emit the SSE event stream; it is not a generic non-streaming
Responses proxy:

```bash
OPENAI_BASE_URL=https://provider.example/v1 \
OPENAI_API_KEY="$YOUR_KEY" \
uv run python -m membench.responses_shim --port 14100

# In another shell, point the harness at the shim:
export OPENAI_BASE_URL=http://localhost:14100/v1
```

Do not put real keys in this README, shell history shared with others, or run
artifacts.

## Configuration

`membench/src/membench/config.py` is authoritative for defaults. CLI flags take
precedence where noted.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GNOSIS_BASE_URL` | `http://localhost:8080` | gnosis HTTP base URL |
| `GNOSIS_TOKEN` | `membench-token` | gnosis request token |
| `MEMBENCH_TENANT_ID` | `nolgia` | tenant scope |
| `MEMBENCH_SPACE_ID` | `membench` | space scope |
| `MEMBENCH_AGENT_ID` | `membench` | agent scope |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | answerer/judge OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | empty | endpoint credential; use a secret manager or shell environment |
| `MEMBENCH_ANSWER_MODEL` | `gpt-4o-mini` | answer model |
| `MEMBENCH_JUDGE_MODEL` | `gpt-4o` | judge model |
| `MEMBENCH_MAX_ITEMS` | `20` | retrieval depth/limit |
| `MEMBENCH_CONCURRENCY` | `8` | answer and grade workers; `--concurrency` overrides |
| `MEMBENCH_INCLUDE_GRAPH` | `true` | include gnosis graph-QA sections for `context` |
| `MEMBENCH_TIMEOUT` | `300` | HTTP timeout in seconds |
| `MEMBENCH_DATA_DIR` | repository `data/` | default downloaded data directory |
| `MEMBENCH_RESULTS_DIR` | repository `results/` | default run output directory |

The Compose stack has additional gnosis variables for Neo4j, models, embedding
dimensions, extraction, routing, graph, and scoped retrieval. Keep those names
and values in `stack/.env`; do not copy secrets into run notes. When gnosis
points at bare Ollama, set `MEMBENCH_INCLUDE_GRAPH=false` if its graph planner
cannot resolve the configured model name. A real LiteLLM proxy can leave graph
sections enabled when the model route supports them.

## Aging protocol

`membench aging` is a separate, synthetic maintenance protocol. It generates
updated, contradicted, stable, and distractor facts, ingests them in strict
timestamp order, and scores ranked retrieval deterministically without an LLM
judge. Per user it creates two update chains, one two-version contradiction,
two stable controls, and one distractor: `2 * update_versions + 5` add events.
The defaults (`--users 8 --update-versions 3`) therefore create **88** add
events, each as one user+assistant pair.

Supersession ON/OFF is a gnosis deployment setting, not a harness flag. Use a
fresh Compose project/volume for each configuration and distinct output paths:

```bash
# With gnosis running without GNOSIS_READ_SUPERSESSION_ENABLED:
uv run membench aging \
  --seed 7 --users 8 --update-versions 3 \
  --config-label supersession_off \
  --out ../results/aging/off

# Restart gnosis with GNOSIS_READ_SUPERSESSION_ENABLED=true first:
uv run membench aging \
  --seed 7 --users 8 --update-versions 3 \
  --config-label supersession_on \
  --out ../results/aging/on \
  --compare-with ../results/aging/off/aging_results.json
```

The generated synthetic dataset is deterministic for a fixed seed, but the
retrieval results still depend on the gnosis revision, store, and endpoint.
The report includes supersession accuracy, stale-answer rate, stable-fact
retention, false-supersession rate, retrieval-miss rate, and store-growth ratio.

## Outputs and provenance

For a normal run, the output directory contains:

- `ingest_state.json`: completed conversation IDs for ingest resume;
- `answers_<condition>.jsonl`: streamed retrieved context and answer records;
- `graded_<condition>.jsonl`: streamed scores and judge responses;
- `results.json`: run settings and aggregate metrics; and
- `report.md`: rendered per-category report.

The aging command writes `dataset.json`, `ingest_state.json`, `probes.jsonl`,
`aging_results.json`, and `aging_report.md`. Run output and downloaded data are
ignored by Git. Keep `RESULTS.md` as the human-readable benchmark ledger and
record machine-state provenance alongside any score you publish.

## Repository layout

```text
stack/compose.yaml       Neo4j + gnosis Compose stack
data/                    downloaded data (ignored) and frozen LME ID list
membench/
  src/membench/datasets.py   download/load/normalize datasets
  src/membench/ingest.py     ordered turn-pair ingestion and resume state
  src/membench/answer.py     context/search retrieval and answer prompts
  src/membench/grade.py      LongMemEval and LOCOMO scoring
  src/membench/aging.py      synthetic supersession protocol
  src/membench/run.py        download/run/aging CLI
  src/membench/responses_shim.py  Responses-to-chat compatibility shim
  tests/                     fixture-based unit tests
docs/                        benchmark design and limitations
RESULTS.md                   detailed run ledger
```

## Development and CI

Run the same checks used by [`test.yml`](.github/workflows/test.yml) from
`membench/`:

```bash
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

The CI workflow installs Python 3.13, runs those four project checks, and does
not start Docker Compose, download benchmark data, call gnosis, or run a paid
benchmark. Compose syntax can be checked independently without contacting a
service:

```bash
docker compose -f ../stack/compose.yaml config --quiet
```

This repository intentionally keeps detailed benchmark tables and historical
deviations in [`RESULTS.md`](RESULTS.md), rather than presenting a changing
model/provider inventory as a timeless README claim.
