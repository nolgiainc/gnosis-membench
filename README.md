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

## How it works

```
benchmark JSON ──ingest──▶ gnosis (/v1/memories, infer=true, turn by turn)
question ───────retrieve─▶ gnosis (/v1/memory/context  OR  /v1/memories/search)
retrieved text ─answer───▶ LLM (sees ONLY the retrieved memory, never the raw history)
hypothesis ─────grade────▶ official scorer (LLM judge / F1 / BLEU-1)
                └──▶ results.json + report.md (paper-style category tables)
```

- One gnosis `user_id` per benchmark conversation, one `session_id` per
  benchmark session, one extraction-mode add per turn.
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
`GNOSIS_TENANT_ID`, default `bromigos`).

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
    run.py            CLI: membench download | membench run
  tests/              fixture-based unit tests (loaders, graders, request shapes)
```

## Development

```bash
cd membench
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
```
