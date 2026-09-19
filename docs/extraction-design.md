# LLM fact extraction at ingest — design spec

Status: implemented — edu-v1 shipped Run 5 (gnosis PR #14, 2026-07-04); edu-v2.0 shipped L-25 (2026-08-04) · Owner: gnosis · Date: 2026-07-02

## 1. Why this is the lever

As of this spec's date (2026-07-02), gnosis ingests **verbatim turns with zero
LLM extraction**: every
`/v1/memories` add with `messages` + `infer=true` writes one `said_user` /
`said_assistant` `Fact` per message (`backend.py::_add_turn_memories`,
`add_message`), embeds it, and that is the entire write-side intelligence.
On the frozen LOCOMO subset-3 config this scored **59.5 J (context) / 61.3 J
(search)** excl. adversarial — a dated-RAG store. Every published leader
distills at ingest:

| System | LOCOMO overall J | Ingest representation |
|---|---|---|
| gnosis Run 3 (ours, gpt-5.5 judge) | 59.5 / 61.3 | verbatim turns |
| Zep (mem0 paper's eval) | 66.0 | entity/edge triples + fact strings, bi-temporal |
| mem0 | 66.9 | extracted fact strings + ADD/UPDATE/DELETE |
| mem0-graph | 68.4 | + entity graph (**graph adds only +1.56 J**) |
| full-context | 72.9 | — |
| EMem (arXiv 2511.17208, gpt-4o-mini end-to-end) | **0.780** | enriched EDUs (event-centric units), append-only |

Two findings from the primary sources drive the design choice:

1. **The representation is the lever, not the graph.** EMem's own ablation:
   EMem (dense retrieval over EDUs, no graph propagation) ties EMem-G
   (graph + PPR) at **0.780** on LOCOMO. mem0's paper: graph memory adds
   **~2%** (66.88 → 68.44). Zep's edges carry a *natural-language fact
   string* — the retrieval payload is prose, the graph is scaffolding.
2. **Append-only beats destructive updates for this workload.** EMem does
   **no** invalidation, dedup, or updates — "our design aims to preserve
   information in a non-compressive form and make it more accessible, rather
   than more lossy" — and resolves contradictions at QA time by timestamp
   recency, scoring **94.4%** on LongMemEval knowledge-update (vs 78.2
   full-context). Graphiti never deletes either: contradicted edges get
   bi-temporal `invalid_at`/`expired_at`. Only mem0 does destructive
   UPDATE/DELETE, and it is the weakest of the three on temporal questions.

### 2026 literature check (does anything change the picture?)

EMem's 0.78 is no longer the frontier, but the successors reinforce rather
than overturn this design:

- **Mnemis** (Microsoft, arXiv 2602.15313): 89.8 J in EMem's exact
  gpt-4o-mini setting — but the gains are **retrieval-side** (dual-route
  System-1 dense + System-2 global selection). Ingest representation is
  still distilled units in a hierarchical graph.
- **EverMemOS** (arXiv 2601.02163): ~92.3–92.7 — ingest-time "MemCells":
  *atomic facts + time-bounded signals*, i.e. exactly the EMem-style
  dated, self-contained unit, plus thematic consolidation.
- **Memory-R2** (arXiv 2605.21768): 80.99 J with a **7B** model by
  RL-training the extraction policy — more evidence that extraction quality
  dominates backbone size.
- Caveat: cross-paper LOCOMO numbers use different answer backbones and
  judges (our numbers are gpt-5.5-judged; mem0's table is gpt-4o-mini);
  treat all cross-vendor comparisons as directional.

Conclusion: **event-centric extracted units at ingest** is the consensus
mechanism across everything at or above 0.78. Retrieval-side upgrades
(Mnemis-style) are a later, separate lever.

## 2. Decision

**Adopt EMem-style enriched event units** ("extracted facts"): short,
self-contained, entity-normalized, absolutely-dated natural-language
statements with source-turn attribution, written as ordinary `Fact` nodes
alongside — not instead of — the existing verbatim `said_*` facts.

**Rejected alternatives:**

- **Triplet extraction (Zep/Graphiti-style edges, or the SDK's
  `GNOSIS_EXTRACT_ENTITIES/RELATIONS` path).** Triples fragment discourse —
  EMem: "a retrieval step must find and recombine several triples to
  reconstruct the event, and fine-grained temporal or participant
  constraints can be lost." Even Graphiti's edges lean on a prose `fact`
  string for retrieval. mem0's measured graph delta is ~2%. Cost is a full
  extra pipeline (extract → resolve → dedupe → invalidate, 4+ LLM calls per
  episode in Graphiti).
- **mem0-style ADD/UPDATE/DELETE memory management.** Two LLM calls per
  add, and the UPDATE/DELETE path destructively rewrites memory based on an
  LLM judgment over 5-nearest-neighbor context. We have direct local
  evidence against silent destructive merging: the SDK's write-time fact
  dedup (`GNOSIS_FACT_DEDUPLICATION_ENABLED`, default true) already
  **swallows near-duplicate adds into an existing fact** (the add returns
  `event: "UPDATE"` with `metadata.deduplicated: true` and the survivor's
  id — provider-surface.md §add), which loses distinct content with no
  review step. mem0's own guidance elsewhere in gnosis is review-first
  dedup for exactly this reason. Do not build a second destructive path.
- **Session-level batch extraction (EMem's literal setup).** EMem extracts
  once per completed session. gnosis is a streaming gateway (Discord/hermes
  turns arrive live); we adapt to **per-add extraction over the new
  messages with a recent-context window**, which is also what mem0 v3 does
  (last-10-messages context). Session-end batch consolidation can come
  later as a `consolidation` job.

## 3. Extraction prompt

Adapted from EMem's `conversation_edu_extraction_v1` (repo
`KevinSRR/EMem`, one-shot, structured output), with: (a) an explicit
NEW-vs-CONTEXT turn split for streaming ingest, (b) Graphiti's
no-hallucinated-dates rules for `event_date`, (c) mem0's empty-output and
same-language guardrails, (d) Discord/hermes content handling. One LLM call
per add request.

### System prompt (exact text)

```
You are a memory extraction system for a long-term conversational memory
store. Given recent conversation context and one or more NEW turns, your
task is to decompose the NEW turns into memory units - short statements
that are minimal yet complete in meaning. Each unit expresses a single
fact, event, preference, plan, or proposition and is atomic (not easily
divisible further while still making sense). Preserve all substantive
information from the NEW turns - no detail should be lost.

Requirements:
1. Each unit must be a self-contained statement that can be understood
   independently, without reading any other unit or the conversation.
2. Never use pronouns or ambiguous references ("he", "it", "the event",
   "that place"). Use specific names, and consistently use the most
   informative name for each entity in all units. Resolve references to
   things said in CONTEXT turns by incorporating the specific details into
   the unit so it stands alone.
3. Extract only from the NEW turns. CONTEXT turns are for reference
   resolution only - do not re-extract information that appears solely in
   CONTEXT turns.
4. The units must collectively capture everything substantive in the NEW
   turns: facts, events, decisions, preferences, plans, concerns, personal
   attributes, relationships, and states - regardless of how minor a
   detail may seem. Do not extract conversational pleasantries, greetings,
   acknowledgements, or filler.
5. Resolve all relative time references ("yesterday", "next month", "last
   Saturday", "this quarter") to absolute dates or periods using the
   conversation date given in the header. Include the temporal context in
   the unit text where it is needed for the unit to stand alone.
6. For each unit, set event_date to the ISO date (YYYY-MM-DD) when the
   described event happened or will happen, if it is stated or can be
   resolved from the conversation date. If the unit is an ongoing state or
   preference, or no date is stated or resolvable, set event_date to null.
   Never invent dates. If only a month or year is mentioned, use its first
   day.
7. For each unit, list source_turn_ids: the turn numbers of the NEW turns
   the unit was extracted from (a unit may span several turns).
8. For each unit, list entities: the specific named entities mentioned in
   the unit (people, places, organizations, products, projects, works),
   using the same canonical names as in the unit text. Do not list dates,
   generic nouns, or feelings.
9. Speaker attribution matters: state who did, said, prefers, or plans
   each thing, using the speaker's name as given in the turn labels.
10. Chat-platform content: treat user mentions (e.g. "@name" or "<@123>")
    as references to those people and resolve them to names where
    possible. Ignore bot commands, emoji reactions, and formatting markup
    unless they carry substantive meaning. Summarize the substance of
    links, code blocks, or attachments only as described by the speakers.
11. Write units in the same language as the conversation.
12. If the NEW turns contain nothing substantive, return an empty list.

Return JSON only, in this exact format:
{"facts": [{"text": "...", "source_turn_ids": [1],
            "entities": ["..."], "event_date": "YYYY-MM-DD" | null}]}
```

### User message template (exact text)

```
Conversation date: {session_date_or_ingest_date}
Speakers: {speaker_names}

CONTEXT turns (reference only, do not extract):
{numbered_context_turns_or_"(none)"}

NEW turns (extract from these):
{numbered_new_turns}
```

Turns render as `Turn {n}: {speaker}: {content}`; numbering is continuous
across CONTEXT and NEW so `source_turn_ids` are unambiguous, and only NEW
turn numbers are valid in `source_turn_ids`. `speaker` is `user` /
`assistant` role mapped to display names when the caller supplies them
(hermes passes Discord display names in message content or metadata;
membench passes LOCOMO speaker names via roles).

### One-shot exemplar

Include one fixed exemplar (system-adjacent, as EMem does): a 6-turn
dated exchange whose gold output demonstrates (i) multi-turn units with
`source_turn_ids: [3, 5]`, (ii) "next month" resolved to an absolute
month, (iii) entity canonicalization ("the symposium" → full event name),
(iv) an ongoing preference with `event_date: null`, and (v) pleasantries
producing no units. EMem's published exemplar (Alice/Bob, Tokyo symposium,
March 2024) can be reused nearly verbatim; keep it under ~600 tokens.

Prompt is versioned: `extraction_version: "edu-v1"` stored in metadata so
future prompt changes are distinguishable in the graph and in benchmarks.

## 4. Ingest integration

Touch points (gnosis repo — read-only survey; implementation is a gnosis
PR):

- `backend.py::_add_turn_memories` (the `/v1/memories` `messages` +
  `infer=true` path) and `backend.py::add_message` (the `/v1/messages`
  path). Both currently do `short_term.add_message` + verbatim
  `said_{role}` `add_fact`.
- New step, after the verbatim writes, gated by the feature flag:
  1. Fetch recent session context: last `GNOSIS_FACT_EXTRACTION_CONTEXT_TURNS`
     (default 10) messages for the scope's session from `short_term`,
     excluding the just-added ones.
  2. Build the prompt above. Conversation date = request
     `metadata.session_date` if present (membench supplies it), else
     ingest date. This finally gets haystack dates into memory content
     without mutating benchmark text (`--inline-dates` becomes obsolete).
  3. One LiteLLM chat call, JSON response format, model
     `GNOSIS_FACT_EXTRACTION_MODEL` (defaults to `GNOSIS_LLM`).
  4. Validate against a Pydantic schema (`text` non-empty, `source_turn_ids`
     subset of NEW turn ids, `event_date` parses or null). Drop invalid
     units, never the batch.
  5. Write each unit as a `Fact` (§5) with `generate_embedding=True`.
- **Failure policy: extraction is strictly additive.** Any LLM error,
  timeout, or schema failure logs a structured warning and the request
  succeeds with the verbatim facts already written — identical to today's
  behavior. Never fail or delay-fail an add on extraction.
- **Granularity:** callers should send turn-pairs (user + assistant in one
  `messages` array) so extraction runs once per exchange. membench's
  `ingest.py` currently posts one turn per add; change it to post
  user+assistant pairs per add (LOCOMO alternates speakers). Single-message
  adds still work — they just cost one call each.
- **Response shape:** each extracted unit is appended to the add response's
  `results` with `event: "ADD"` and its own `memory_id`, after the verbatim
  results. This is contract-additive (`results` is already a list).

## 5. Data model

Extracted units are ordinary long-term `Fact` nodes — same label, same
vector index, same scope mechanics — so search, context assembly, list,
PATCH/DELETE, federation, redaction, and the filter DSL all work unchanged.

| Field | Value |
|---|---|
| `subject` | `_user_identifier(scope)` — same as `said_*` facts (scope reads keep working) |
| `predicate` | **`fact`** (new constant `EXTRACTED_FACT_PREDICATE`, joining `memory` and `said_*` in `memory_provider.py`) |
| `object` | the unit text (embedded) |
| `created_at` / `updated_at` | ingestion time (SDK-set) — **transaction time** |
| `metadata` | scope tags (as today) + extraction fields below |

Extraction metadata (inside the fact's metadata JSON, alongside caller
metadata such as membench's `session_date` / `turn_index`):

```json
{
  "extracted": true,
  "extraction_version": "edu-v1",
  "extraction_model": "openai/gpt-5.5",
  "event_date": "2023-05-07",            // event time; null if unknown
  "entities": ["Caroline", "Melanie"],
  "source_memory_ids": ["<said_* fact uuids from this add>"],
  "source_turn_ids": [3, 4]              // prompt-local turn numbers
}
```

- **Bi-temporal seam:** `created_at` is transaction time; `event_date` is
  event time (Graphiti's `valid_at` analog, extracted under its
  never-hallucinate rules). A later invalidation feature adds
  `invalid_at`/`expired_at` — the schema slot is reserved now, cheap
  because it's metadata.
- **Backward compatibility:** `said_*` verbatim facts keep being written
  (EMem's non-compressive principle; also our provenance/audit trail and
  the substrate for re-extraction when the prompt improves). Existing
  graphs need no migration: old facts simply lack `extracted`. Read paths
  need zero changes for v1 — extracted units enter the same relevance-ranked
  candidate pools (`search_facts`, the PR #7 context path) and win on
  similarity because they are denser and dated. `_PRIVATE_METADATA_KEYS`
  stays as is; extraction metadata is intentionally public (useful to
  clients).
- **Read-path follow-up (separate PR, only if measured):** render
  `event_date` instead of `created_at` in the context one-liners
  (`- [7 May 2023] ...`) when present, and add the EMem QA-time
  instruction "resolve contradictions by preferring more recent memories"
  to the context header.

## 6. Update / contradiction policy (v1)

**Coexist, append-only.** No LLM-driven UPDATE/DELETE, no write-time
merging of extracted facts:

- EMem is append-only and leads LOCOMO temporal *and* LongMemEval
  knowledge-update; contradiction resolution happens at read time via
  timestamps ("prioritize more recent memories").
- Graphiti, the most sophisticated updater, still never deletes — it sets
  `invalid_at` (event time) + `expired_at` (transaction time) on the
  superseded edge, and its LLM only *flags* contradictions
  (`resolve_edge` → `contradicted_facts`); the state change is
  deterministic code. That is the v2 blueprint: a
  Graphiti-style contradiction pass that stamps `invalid_at` on superseded
  extracted facts, review-first like our dedup/consolidation surfaces.
- Cautionary local evidence: the SDK's write-time dedup already silently
  swallows near-duplicate adds into an existing fact (returned as
  `event: "UPDATE"`, `deduplicated: true`) — a destructive merge with no
  review. **For extracted-fact writes, bypass write-time dedup**
  (`deduplicate=False` on the `add_fact` call if the SDK exposes it, else
  accept and monitor the swallow rate via the `UPDATE` event count in
  benchmark stats). Two same-day extractions of the same statement are
  harmless duplicates; a swallowed distinct dated event is a lost answer.
  Prompt rule 3 (extract only from NEW turns) already bounds re-extraction
  across overlapping context windows.

## 7. Cost / latency model

Per turn-pair add, extraction adds **one** LLM call (vs mem0's two,
Graphiti's four-plus):

| Component | Estimate |
|---|---|
| System prompt + exemplar | ~1,100–1,500 tokens |
| Context window (10 turns) + new turns | ~400–900 tokens |
| Output (3–8 units × ~25 words + JSON) | ~150–450 tokens |
| **Per call** | **~2.2k in / ~0.3k out** |

LOCOMO subset 3 (1,451 turns → ~726 turn-pair calls): **~1.6M input /
~0.25M output tokens** total. Via the self-hosted LiteLLM gpt-5.5 route this
is quota/wall-clock bound rather than metered; if routed to a metered
endpoint, at typical frontier-mini list prices this is single-digit
dollars per full subset ingest. Expected unit volume: EMem produced ~20
EDUs/session (~553/conversation) on LOCOMO; at turn-pair granularity
expect similar totals (~1.5–3k extracted facts for subset 3), roughly
doubling `Fact` count — negligible for Neo4j and the vector index at this
scale.

Latency: ~2–5s per call at gpt-5.5. Implications per `GNOSIS_WRITE_MODE`:

- **`sync` (benchmark + current prod default):** extraction runs in the
  request path; adds go from ~130ms to ~2–5s. Fine for membench (ingest
  3.2 min → ~40–70 min sequential; membench can add client-side
  concurrency of 4–8 across conversations to bring it back under ~15 min —
  conversations are isolated users, so ordering only matters within a
  session).
- **`buffered`:** the SDK buffers graph writes, but extraction as designed
  runs before the write is enqueued, so the LLM call still lands in the
  request path. For hermes/Discord production latency, v1.1 should move
  extraction into a background task (asyncio task queue bounded by
  `GNOSIS_EXTRACTION_MAX_CONCURRENCY`, reusing the existing pending-write
  bookkeeping), the same posture as LangMem's background
  `ReflectionExecutor`. v1 ships sync-path-only behind the flag; Discord
  enablement waits for the async worker unless measured latency is
  acceptable.

## 8. Benchmark plan (membench)

> **What actually shipped (post-hoc note):** this landed as **Run 5** (gnosis
> PR #14), not Run 4. Run 4 became the recall-filter ablation (gnosis PR #13,
> which did not reproduce). The "Run 4" references below are the original
> 2026-07-02 prediction — see RESULTS.md for the as-run record.

This is a **write-path** change: unlike PRs #6/#7, it **requires
re-ingest** into a fresh Neo4j.

1. **Harness change:** `ingest.py` posts user+assistant turn-pairs per add
   (one `messages` array of 2); keep `session_date` in metadata (now
   consumed by extraction); drop `--inline-dates` from the protocol.
2. **Conditions:** Run 4 = extraction ON, fresh ingest, frozen config
   (subset 3, depth 20, gpt-5.5 answer + judge via responses shim, same
   embeddings). Baseline = Run 3 (59.5/61.3) — same read path, same
   answer/judge route, so the delta isolates extraction. If turn-pair
   batching is suspected of moving numbers on its own, run an optional
   control: extraction OFF with turn-pair ingest (cheap: ingest-only +
   answer, no new gnosis build).
3. **Report both conditions** (context and search) as always, plus the
   mechanism stats: extracted facts per session (expect ~15–25, per
   EMem's 20.3), extraction failures/dropped units, `UPDATE` (dedup
   swallow) rate, avg retrieved chars, % retrievals dated with
   *event* dates, % "no information" answers, ingest wall-clock and token
   totals.
4. **Expected gains** (directional, from EMem/mem0 evidence): temporal
   42.2 → mid-50s+ (extraction's biggest measured win: EMem 0.771 vs mem0
   0.504 there; absolute dates in content are the mechanism), multi-hop
   40.5 → ~50+ (self-contained multi-turn units), open-domain 38.1 → ~45+,
   single-hop holds (already 76.5). Overall target: **66–70 J excl.
   adversarial** — at or past mem0/Zep's published band. Watch adversarial:
   denser retrieval has previously reduced abstention (Run 2); the "no
   information" instruction stays in the answer prompt.
5. **Record in RESULTS.md** as Run 4 with the gnosis commit and flag set,
   per the frozen-config protocol.

## 9. Feature flags and rollout

Do **not** overload `GNOSIS_EXTRACT_ENTITIES/RELATIONS` — those gate the
SDK's entity/relation graph pipeline (a different mechanism, off by
default, request-opt-in via `_extraction_policy`). New settings:

| Setting | Default | Meaning |
|---|---|---|
| `GNOSIS_FACT_EXTRACTION_ENABLED` | `false` | master switch for ingest-time unit extraction on the `messages`+`infer=true` and `/v1/messages` paths |
| `GNOSIS_FACT_EXTRACTION_MODEL` | `""` (→ `GNOSIS_LLM`) | LiteLLM model for the extraction call |
| `GNOSIS_FACT_EXTRACTION_CONTEXT_TURNS` | `10` | short-term context window size |

Reused as-is: `GNOSIS_EXTRACTION_MAX_CONCURRENCY` (bounds the future async
worker), `GNOSIS_WRITE_MODE`. Surface all three in `diagnostics()` like the
existing extraction flags. `infer=false` verbatim adds are never extracted.

Rollout: (1) land behind the flag, default off — zero behavior change;
(2) membench Run 4 (shipped as Run 5 — see §8 note) in the benchmark stack with the flag on and
`GNOSIS_FACT_EXTRACTION_MODEL=openai/gpt-5.5`; (3) if the measured gain
holds, enable for the hermes/Discord deployment once the async extraction
worker (v1.1) removes the request-path latency; (4) backfill option:
because verbatim `said_*` facts are preserved, historical sessions can be
re-extracted offline through the same prompt (a consolidation-style
operator job) — no data loss, no migration.

## 10. Risks

- **Extractor quality sensitivity:** EMem saw large gains moving
  gpt-4o-mini → gpt-4.1-mini on long/heterogeneous turns (861 → 1,392
  EDUs/conv). Don't benchmark with `gemma4`; pin gpt-5.5 and record the
  model in metadata.
- **Preference/attitude loss:** EMem's known weakness (LongMemEval
  single-session-preference 32.2%) — the prompt's rule 4 explicitly keeps
  preferences/attributes, borrowing mem0's category list, but watch
  open-domain in the run.
- **Duplicate accumulation:** append-only + no dedup grows the store;
  acceptable at our scale, and the review-first dedup/consolidation
  surfaces already exist for cleanup.
- **LOCOMO saturation:** 2026 surveys (MemoryArena) show LOCOMO-strong
  systems collapsing on active agentic tasks; keep LongMemEval_S on the
  roadmap as the second measure.

## edu-v2.0 (2026-08-04) — assistant-turn extraction

**Why.** L-23 measured SSA at 41.1% (n=56). Root cause: the edu-v1 exemplar used
two human speakers (Alice and Bob) — there was no demonstration of extracting facts
*attributed to the assistant*. The model treated assistant turns as response scaffolding
rather than a source of durable knowledge.

Evidence from Memanto ([arXiv 2604.22085](https://arxiv.org/abs/2604.22085)): assistant
turns carry commitments, recommendations, how-to guidance, and stated facts that are
exactly as worth remembering as user-disclosed facts. Without explicit extraction,
assistant-perspective memory gaps persist regardless of retrieval improvements.

**Changes from edu-v1.1 → edu-v2.0.**

*Extraction version string:* `"edu-v2.0"` (stored in fact metadata; distinguishes
pre- and post-v2.0 graphs in the same store).

*Rule 15 (new):*
```
15. Extract from BOTH user and assistant turns. Assistant turns carry information just
    as important as user turns: recommendations the assistant made, instructions or
    how-to guidance the assistant provided, facts the assistant stated or explained,
    and commitments the assistant made for future actions. For each such unit, attribute
    it using the speaker label "assistant" (e.g., "The assistant recommended X", "The
    assistant explained that Y", "The assistant committed to Z at the next session").
    Never skip assistant turns because they are responses rather than disclosures — a
    recommendation, a committed reminder, or a how-to instruction from the assistant
    is exactly as worth remembering as a fact the user volunteered.
```

*Exemplar replaced:* The old exemplar (Alice/Bob, two humans) contained no assistant-
attributed facts. The new exemplar uses a user/assistant exchange (Tokyo/Osaka keynote
scenario) and produces 6 facts — 3 user-attributed and 3 assistant-attributed:

| Unit | Turn | Attribution | Content |
|---|---|---|---|
| [0] | 1 | user | user presented at IRS in Tokyo |
| [1] | 1 | user | IRS invited user to Osaka keynote next month |
| [2] | 2 | assistant | The assistant recommended booking Osaka hotels ≥3 weeks out (April = cherry blossom season, prices spike) |
| [3] | 2 | assistant | The assistant stated that the Shinkansen from Tokyo to Osaka takes approximately 2.5 hours |
| [4] | 4 | assistant | The assistant committed to flagging the Osaka keynote venue A/V checklist at the start of the next conversation |
| [5] | 5 | user | user dislikes long-haul flights but would fly anywhere for a keynote |

This gives the model an explicit in-context demonstration that assistant turns are
extraction sources, and that attribution uses "The assistant recommended/stated/committed".

**Backward compatibility.** Facts extracted under edu-v1/v1.1 remain in the graph with
their original `extraction_version`. v2.0 facts are additive; read paths are unchanged.
A re-ingest with v2.0 writes new facts alongside old ones — no migration required.

## References

- EMem: arXiv 2511.17208 (Zhou & Han, UIUC) + github.com/KevinSRR/EMem
  (`src/emem/prompts/templates/conversation_edu_extraction_v1.py`)
- mem0: arXiv 2504.19413; github.com/mem0ai/mem0
  `mem0/configs/prompts.py` (`FACT_RETRIEVAL_PROMPT`,
  `DEFAULT_UPDATE_MEMORY_PROMPT`; Apache-2.0), v3 `ADDITIVE_EXTRACTION_PROMPT`
- Zep/Graphiti: arXiv 2501.13956; github.com/getzep/graphiti
  `graphiti_core/prompts/` (`extract_nodes.py`, `extract_edges.py`,
  `dedupe_edges.py::resolve_edge`,
  `utils/maintenance/edge_operations.py::resolve_edge_contradictions`;
  Apache-2.0)
- LangMem background reflection: langchain-ai.github.io/langmem; Letta
  self-editing memory: letta.com/blog/agent-memory
- 2026: Mnemis arXiv 2602.15313 · EverMemOS arXiv 2601.02163 ·
  Memory-R2 arXiv 2605.21768 · MemoryArena arXiv 2603.07670
- Local: gnosis `backend.py`, `memory_provider.py`, `settings.py`,
  `docs/provider-surface.md`; gnosis-membench `RESULTS.md`,
  `membench/src/membench/ingest.py`
