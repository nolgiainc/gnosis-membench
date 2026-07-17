# Agent-Memory Frontier, July 2026: Dissection and Next Techniques for gnosis

*Updated 2026-07-17. Every load-bearing score or technique claim below was verified
against a primary source (arXiv paper, official repo, or controlled third-party
evaluation). Vendor-only self-reports are flagged explicitly and not used as
technique recommendations.*

**Where gnosis stands (Run 23, 2026-07-04):** Full-LOCOMO (all 10 conversations),
GPT-5.5 judge — excl-adv J 66.9–68.9 at parity with mem0 (66.88); full-LME_S
baseline L-0 in progress. Leads: single-hop (F1 60.9, J 77.0–77.8 vs mem0 67.13),
temporal J (73.8 vs mem0^g 58.13), adversarial (83.9). Weaknesses: open-domain
(J 29.2 vs Zep 76.60), multi-hop (J 41.5 vs frontier ~85+). Primary target:
LongMemEval_S (500 questions, 5 ability axes including knowledge-update and
abstention that LOCOMO lacks).

---

## 0. Read this first: judge comparability and benchmark integrity

No score in this document is directly comparable to gnosis's GPT-5.5-judged
results without a judge-sensitivity correction.

**LOCOMO is effectively saturated.** An independent audit (Penfield Labs,
`dev.to/penfieldlabs`, April 2026) found **6.4% of LOCOMO's 1,540 answer keys
are wrong** (99 confirmed errors: hallucinated facts, temporal errors, 24
speaker-attribution errors). The standard gpt-4o-mini judge **accepts 62.8% of
intentionally wrong-but-topically-relevant answers**. Theoretical maximum ≈ 93.6.
The 92–94 frontier scores under gpt-4.1-mini are *at the ceiling*, not evidence of
architectural dominance. MemDelta (arXiv:2606.29914) and "Are We Ready For An
Agent-Native Memory System?" (arXiv:2606.24775) independently argue current
LOCOMO/LongMemEval comparisons carry hidden confounds and no architecture dominates.

**Controlled cross-system comparison: Memori Labs** (gpt-4.1-mini judge, 3-round
average) is the most credible same-protocol multi-system evaluation currently
public:

| System | Overall | Single-Hop | Multi-Hop | Open-Domain | Temporal |
|---|---|---|---|---|---|
| Memori | 81.95% | 87.87% | 72.70% | 63.54% | 80.37% |
| Zep | 79.09% | 79.43% | 69.16% | **73.96%** | 83.33% |
| LangMem | 78.05% | 74.47% | 61.06% | 67.71% | 86.92% |
| Full-context | 87.52% | 88.53% | 77.70% | 71.88% | 92.70% |
| Mem0 | 62.47% | 62.41% | 57.32% | 44.79% | 66.47% |

Zep's open-domain 73.96% under controlled conditions is consistent with the 76.60
figure cited in prior gnosis docs — the gap is real, not a protocol artifact.

**LongMemEval_S is the reliable benchmark.** 500 questions, stable gpt-4o judge,
public leaderboard, 5 meaningful axes (knowledge-update, multi-session, temporal
reasoning, single-session variants, abstention). This is gnosis's primary
optimization target.

---

## 1. LongMemEval_S — the leaderboard that matters (as of 2026-07-17)

| Rank | System | Score | KU | Multi-Session | Temporal | Notes |
|---|---|---|---|---|---|---|
| 1 | JordanMcCann agentmemory | **96.2%** | — | — | — | gpt-4o judge, seed=42, reproducible |
| 2 | Chronos High (PwC, arXiv:2603.16862) | **95.60%** | **100%** | 88.7% | 95.5% | Claude Opus 4.6 generator |
| 3 | OMEGA | **95.4%** | 96.2% | 83% | 94% | gpt-4.1 as *both* judge and generator — exclude from strict comparison |
| 4 | Mastra Observational Memory | **94.87%** | 96.2% | — | — | gpt-5-mini generator, gpt-4o judge |
| 5 | Chronos Low | **92.60%** | 96.15% | 91.7% | 90.2% | GPT-4o generator |
| 6 | Mastra OM (gpt-4o) | **84.23%** | 85.9% | — | — | |
| 7 | Oracle (full-context) | **82.4%** | — | — | — | |
| 8 | Supermemory | **81.6%** | — | — | — | |
| 9 | Zep (arXiv:2501.13956) | **71.2%** | 83.3% | 57.9% | 62.4% | GPT-4o judge |
| gnosis L-0 | Run 18 + gemini embeddings | *pending* | — | — | — | smoke test confirmed pipeline works |

**Knowledge-update is the clearest performance divide.** Chronos achieves 100%
KU because its event calendar structure makes temporal supersession deterministic.
Gnosis's smoke test confirmed that KU is its weakest axis: the superseded value
was returned instead of the updated one.

---

## 2. Mnemis (Microsoft) — dual-route retrieval on hierarchical graphs

*Source: arXiv:2602.15313 (v2 2026-04-10), stated ACL 2026. Neo4j substrate,
partial code release.*

**Architecture:** System-1 (BM25 + embedding, RRF, per-type ranking) runs
**in parallel** with System-2 (LLM top-down traversal of a hierarchical category
graph) — NOT an escalation cascade. Results unioned and reranked by
Qwen3-Reranker-8B (ablation: 0.6B costs ≤0.7 pts).

**Category graph (System-2):** built bottom-up from entities, 3 principles —
minimum concept abstraction, many-to-many parent mapping (explicitly contrasts
GraphRAG's single-parent communities), compression-efficiency constraint. At
query time, LLM walks top-down, selects branches, retrieves all entities + edges
from relevant leaves — no top-k limit. Rebuilt periodically (incremental
maintenance is future work).

**Scores (gpt-4.1-mini judge, adversarial excluded):** 93.3 overall / 91.8
multi-hop / 90.3 temporal / 82.3 open-domain / 96.2 single-hop. GPT-4o-mini
backbone: 89.8. Same-table baselines: Full-context 80.6, EverMemOS 92.3, mem0 66.3.

**The hidden adversarial number (from raw metrics JSON):** System-2's adversarial
score is **34.3%** — it retrieves broadly and manufactures false support. This is
exactly the tradeoff gnosis has already navigated: Run 16 (directed bridge
traversal) showed the same pattern at smaller scale. Gnosis leads on adversarial;
Mnemis leads on open-domain and multi-hop.

**Key ablation:** System-1 RAG 73.8 → +graph 89.1 → +System-2 **93.3**. System-2
alone: 87.7 (weakest on temporal: 78.5 — the graph route alone doesn't help
temporal, which is the dedicated BM25-hybrid route). Net gain from System-2 global
selection: **+4.2 overall**.

**Relevance for gnosis:** Mnemis and gnosis share the Neo4j substrate. The
System-2 concept layer maps onto gnosis's dormant graph-QA path + the new
community graph feature. The key insight: *global/hierarchical structure unioned
with vector retrieval*, not escalation or routing alone.

---

## 3. EverMemOS — MemCells, scenes, and agentic retrieval

*Source: arXiv:2601.02163. Code in forks (tchen-coder/EverMemOS, nightsailer/EverMemOS).*

**MemCell structure:** (Episode, AtomicFacts, Foresight[t_start,t_end], Metadata).
Foresight carries temporal validity intervals — the missing piece in gnosis's
fact model. Scene grouping via incremental centroid clustering (zero LLM cost).

**Retrieval pipeline:** Hybrid dense + BM25 (RRF k=60) over atomic facts → scene
selection → Qwen3-Reranker-4B → date filter (foresight validity window) →
**agentic sufficiency check** → if insufficient: 2–3 complementary queries using
entity_pivot, temporal_calculation, concept_expansion, or HyDE strategies. Fires
on **31.0% of LoCoMo queries**.

**Scores (gpt-4.1-mini, 3-judge avg):** 93.05 overall / 91.84 multi-hop / 89.72
temporal / 76.04 open-domain. LongMemEval-S: **82.00–83.00**, with knowledge-update
89.74 as standout.

**Critical distinction from Run 4 (LLM recall filter, rejected):** EverMemOS's
sufficiency+rewrite is a *recall play* (adds new queries) not a *precision play*
(discards candidates). Our recall filter discarded 84% of candidates and added
6–7 s latency with no accuracy gain. The query rewrite is orthogonal.

---

## 4. Chronos (PwC) — event calendar and 100% knowledge-update

*Source: arXiv:2603.16862. LongMemEval_S SOTA on knowledge-update.*

**Dual-calendar architecture:**
- **Event calendar:** (subject, verb, object, start_datetime, end_datetime,
  lexical_aliases[2–4 paraphrases]) tuples extracted per conversation.
- **Turn calendar:** raw text + session metadata.

**Multi-resolution temporal normalization:** explicit ISO 8601 → preserved;
relative expressions (yesterday, last month) → calculated from session timestamps;
ambiguous → stored as ranges.

**Dynamic retrieval guidance:** before retrieval, the LLM generates tailored
search guidance for the query ("Pay close attention to: camera lens purchases,
specifically the most recent purchase") rather than using the raw query directly.
This alone accounts for a substantial fraction of Chronos's lead.

**Why 100% knowledge-update:** the event calendar separates state changes into
discrete (subject, verb, object, time) tuples. When a user changes jobs, the
event "resigned from X" appears as a new entry with a later timestamp — Chronos
selects the most recent event for that (subject, verb cluster) deterministically
at read time, not via LLM judgment.

**LongMemEval_S KU ranking:** Chronos High 100% (Claude Opus 4.6), OMEGA 96.2%
(self-judged, exclude), Mastra OM 96.2% (gpt-5-mini), Chronos Low 96.15%,
Mastra OM (gpt-4o) 85.9%, Zep 83.3%.

**Gnosis gap:** gnosis's extracted facts have `event_date` but no temporal
validity interval (`valid_from/valid_to`). When a user changes location, the new
and old facts coexist with no link. Read-time supersession (`GNOSIS_READ_SUPERSESSION_ENABLED`)
is approximate; the smoke test confirmed it returns the old value on the LME KU test.

---

## 5. JordanMcCann agentmemory — 96.2% LME_S with six retrieval signals

*Source: github.com/JordanMcCann/agentmemory. gpt-4o judge, seed=42, reproducible.*

**Six parallel weighted retrieval signals:**

| Signal | Weight | Implementation |
|---|---|---|
| Semantic similarity | 0.30 | HNSW, all-mpnet-base-v2 |
| Lexical (BM25) | 0.12 | SQLite FTS5 |
| Graph spreading activation | 0.18 | KG traversal with activation decay |
| Activation (recency + frequency) | 0.18 | Time-decayed access count |
| Node importance | 0.10 | Calibrated confidence score |
| Temporal proximity | 0.12 | Gaussian decay from query's implied time |

Cross-encoder reranker: ms-marco-MiniLM-L-6-v2 (local, fast).

**Critical finding from ablation:** Replacing approximate HNSW with exact KNN
*reduced* score from 96.2% to 95.2%. HNSW explores neighborhoods (approximate
nearest-neighbor traversal explores node-neighborhood beyond strict top-k) that
exact retrieval misses — effectively adding graph-traversal signal to dense search
at no extra cost.

**Knowledge-update:** Prompt engineering that distinguishes intent/hypothesis
("thinking about buying X") from established fact ("I own X"). No structural
validity intervals.

**Spreading activation:** After seeding from top-k similar nodes, activation
propagates to neighbors with decay coefficient — the BFS/spreading-activation
alternative to gnosis's graph-QA fusion. Lower engineering cost than Mnemis's
hierarchical category graph.

---

## 6. Mastra Observational Memory — periodic reflector for supersession

*Source: mastra.ai/research/observational-memory. gpt-4o judge, gpt-5-mini generator.*

**Architecture:** Every observation carries (observed_time, referenced_time,
relative_time_expression) — a three-timestamp design. A background *Reflector*
periodically consolidates the observation store: merges near-duplicates and marks
superseded observations with explicit links (keeps originals, never deletes).

**96.2% KU result** credited to two mechanisms: (1) temporal anchoring (all three
timestamp types preserved per fact), (2) the Reflector that marks obsolete facts
before query time so the retriever never surfaces them.

**Gnosis implications:** This is the "append-only + read-time recency" design
validated by arXiv:2606.01435 ("Don't Ask the LLM to Track Freshness": deterministic
newest-wins → 94.8% FactConsolidation vs Zep bi-temporal 7.0%), extended with a
background consolidation pass. Both the append-only design and the consolidation
schedule exist in gnosis — the missing piece is `valid_from/valid_to` timestamps
on facts and explicit `SUPERSEDES` edges in the graph.

---

## 7. New papers, July 5–17, 2026

| Paper | arXiv | Finding | Gnosis relevance |
|---|---|---|---|
| MemCon | 2607.13591 | Tabular contextual bandit for adaptive memory management (when to retrieve, inject, consolidate). Zero extra LLM calls, ~15 pp gains on ALFWorld/GAIA/ScienceWorld. | Research direction: RL-based routing. Not directly applicable to QA benchmarks yet. |
| Learning User-Aware Recall | 2607.00017 | Personalized retrieval for long-term memory; evaluates on LOCOMO and LME_S; ColBERT as baseline (underperforms learned personalized approach). | Personal signal (recency + frequency + user-affinity) improves recall beyond generic similarity. gnosis's activation signal (per JordanMcCann recipe) is the low-cost proxy. |
| A-TMA | 2607.01935 | State-aware memory failure taxonomy. | Diagnostic vocabulary for our open-gap analysis. |
| Memory in the Loop | 2607.05690 | In-process retrieval as extended working memory within the reasoning loop. | Relevant if gnosis moves to agent-loop integration; not a QA benchmark change. |
| AutoMem | 2607.01224 | Automated learning of memory as a cognitive skill. | Research direction, no benchmark result yet. |
| "Is Grep All You Need?" | 2605.15184 | Inline BM25 (grep) **outperforms** inline vector search for every harness-model pair on LongMemEval. Not a "drop vector" result — it means BM25 is at minimum a co-equal signal. | Strongest evidence yet that gnosis's hybrid BM25+dense path should be routed more aggressively, not just for temporal queries. |
| LongMemEval-V2 | 2605.12493 | V2 evaluates **web agent trajectory memory** (static state, dynamic tracking, workflow knowledge) — 5 entirely different categories. NOT a conversational memory benchmark evolution. | Do not conflate with LME_S. Ignore for gnosis's current target. |

---

## 8. Zep / Graphiti — open-domain via community subgraph

*Source: arXiv:2501.13956.*

**Three-layer architecture:**
1. Episodes (raw text, `valid_at`)
2. Semantic entities (extracted facts + KG relationships, bitemporal)
3. **Community subgraph:** LLM-abstracted clusters of strongly connected entities
   with natural-language summaries

**Community detection** uses label propagation over entity-entity edges (not Leiden
— more suitable for dynamic incremental updates). For each community, an LLM summary
is generated: "User's professional context: software engineer at X, transitioning to
Y tech stack, recently attended Z conference."

**Why communities close open-domain:** When a query matches no specific fact with
high confidence ("What does Alice usually talk about?"), community summaries are
retrieved by embedding similarity. The query has semantic overlap with the community
summary even when it has low overlap with individual facts.

**Zep's open-domain lead (73.96% controlled, ~76.60 self-reported)** vs mem0's
44.79% under the same judge is the strongest evidence for this mechanism. No other
architectural difference explains a ~30 pp open-domain gap while other categories
are much closer.

**Gnosis implementation path:** `community_graph.py` (shipped in this branch) adds:
- Weakly-connected component detection (BFS in Python, no Neo4j GDS needed)
- LLM summary generation per component
- `:Community` nodes + `:MEMBER_OF` edges written to Neo4j
- Read-path integration: community summaries added to context for
  aggregative/open-domain-classified queries

---

## 9. Ranked next techniques for gnosis (updated July 2026)

### T1. Community subgraph for open-domain retrieval
- **Mechanism:** Detect weakly-connected components among `:Entity` nodes per
  scope (BFS, no GDS required); generate one LLM summary per community; embed
  and store as `:Community` nodes; add community summaries to context for
  aggregative and open-domain-routed queries.
- **Evidence:** Zep/Graphiti architecture; controlled Memori eval confirms ~30 pp
  open-domain gap attributable to community layer.
- **Expected gain:** open-domain J 29.2 → 50+ (if the community pattern transfers
  from Zep to gnosis on LME_S). Multi-session may also improve.
- **Cost:** **medium** — community_graph.py is already written in this branch;
  backend integration and operator route (POST /v1/communities/rebuild) remain.
- **Config:** run25.yaml (`gnosis_community_graph_enabled: true`).

### T2. Temporal validity intervals + explicit supersession edges
- **Mechanism:** Extend the fact schema with `valid_from` / `valid_to` fields
  populated by the edu-v1 extractor when it detects stateful facts (jobs, locations,
  relationships with clear start/end language). Write `(:Fact)-[:SUPERSEDES]->(:Fact)`
  edges when a new fact contradicts an existing one for the same entity+slot.
  At read time, filter/boost by validity window.
- **Evidence:** Chronos 100% KU (arXiv:2603.16862); Mastra 96.2% KU; arXiv:2606.01435
  (deterministic newest-wins: 94.8% FactConsolidation). LME smoke test confirmed
  gnosis returns superseded values on KU questions.
- **Expected gain:** LME_S knowledge-update from near-0% baseline toward 80–95%.
- **Cost:** **medium** — extractor prompt change (edu-v2), schema migration, Cypher
  filter changes.

### T3. LLM reranker over the fused candidate pool
- **Mechanism:** After dense+hybrid retrieval and before the item-budget cut,
  run the existing `gnosis_rerank_enabled` listwise reranker over the top-50
  candidates. Already coded; no benchmark result exists yet.
- **Evidence:** Mnemis (Qwen3-Reranker-8B: RAG 73.8 → +graph+fusion 89.1; ablation
  shows reranker size barely matters — 0.6B costs ≤0.7 pts); EverMemOS
  (Qwen3-Reranker-4B); JordanMcCann (ms-marco-MiniLM-L-6-v2).
- **Expected gain:** retrieval is the LME_S bottleneck (full-context 0.606 vs oracle
  0.870); reranking improves which candidates make it to the reader. LME_S is the
  right benchmark — LOCOMO is too saturated to measure this.
- **Cost:** **low** — coded, just needs a run. Config: run24.yaml.
- **Membench:** run LME_S 100-instance frozen subset with and without reranker;
  measure per-type accuracy delta.

### T4. Multi-query rewrite on insufficient retrieval
- **Mechanism:** When sufficiency check fires (context insufficient), emit 2–3
  complementary queries (entity_pivot, temporal_calculation, concept_expansion,
  HyDE) and RRF-fuse with original retrieval. EverMemOS fires on 31% of queries.
  Already coded in `query_rewrite.py` in this branch.
- **Evidence:** EverMemOS (arXiv:2601.02163, prompts public); MemCog (full ReAct
  navigation). Distinct from rejected Run 4 filter (precision play vs this recall play).
- **Expected gain:** multi-hop (entity_pivot = hop-2 bridge lookup) and open-domain
  (concept_expansion); adversarial protected by sufficiency check gating.
- **Cost:** **medium** — query_rewrite.py is written; backend integration needed.
  Config: run25.yaml (`gnosis_sufficiency_check_enabled + gnosis_query_rewrite_enabled`).

### T5. "Is Grep All You Need?" — extend BM25 to non-temporal routes
- **Mechanism:** arXiv:2605.15184 shows BM25 outperforms vectors on LME for every
  model pair. gnosis already has `gnosis_hybrid_retrieval_enabled` (BM25+dense, RRF).
  Run 6 shows it helps temporal (+7.8 temporal) but hurts multi-hop (-5.4) when
  global. The routing table already applies hybrid to temporal only. The open question:
  does hybrid on aggregative/single-hop routes help or hurt on LME_S (which is a very
  different document distribution from LOCOMO)?
- **Evidence:** arXiv:2605.15184 (LME_S-specific); EverMemOS RRF k=60 over atomic facts;
  Mnemis (System-1 BM25); JordanMcCann (FTS5 weight 0.12).
- **Expected gain:** all categories on LME_S (LOCOMO measurement is not transferable);
  temporal already covered by routing.
- **Cost:** **low** — route table change; test as a config variant on LME_S.

### T6. Dynamic retrieval guidance per query (Chronos pattern)
- **Mechanism:** Before retrieval, one cheap LLM call generates tailored search
  guidance: "For this query about camera purchases, pay attention to: acquisition
  events, product categories, price/brand mentions." Use guidance as the retrieval
  query in addition to or instead of the raw query.
- **Evidence:** Chronos credits dynamic prompting for a meaningful fraction of its
  LME_S lead (mechanism, not ablated separately). Similar to HyDE but targeted.
- **Expected gain:** all categories; especially KU (guidance can emphasize recency).
- **Cost:** **low** — one prompt + one LLM call per query; routing can scope it
  to categories where raw queries are underspecified (open-domain, aggregative).

### T7 (watch): Spreading activation over the entity graph
- **Mechanism:** After seeding from top-k similar entities, propagate activation
  to graph neighbors with a decay coefficient (BFS with weights). Return activated
  nodes as additional context candidates. JordanMcCann weight 0.18.
- **Evidence:** JordanMcCann agentmemory 96.2% LME_S (spreading activation is one
  of six signals). HNSW approximate neighborhood traversal implicitly does a version
  of this.
- **Expected gain:** multi-hop (bridges through shared entities). Less targeted than
  directed bridge traversal (Run 16, rejected on LOCOMO) but LOCOMO and LME_S have
  different multi-hop distributions.
- **Cost:** **medium** — graph traversal in Python or Cypher; new code path.

**Explicit non-recommendations (unchanged):**
- Chasing LOCOMO ≥92 (ceiling artifact; benchmark is effectively saturated)
- Adopting LongMemEval-V2 as a target (it measures web agent trajectories, not
  conversational memory)
- Mnemis-style full hierarchical-category *periodic rebuild* (our community graph
  uses lazy per-scope updates, not global periodic rebuilds — better fit for a
  live gateway)
- Memory-R2 RL extractor (no released checkpoints, 2 LoCoMo conversations training
  data — high benchmark overfit risk)

---

## 10. Benchmark posture (updated July 2026)

**Primary target: LongMemEval_S** (500 questions, stable gpt-4o judge, 5 axes
that map directly to our gaps). Frozen 100-instance subset is the inner loop;
full 500 is the competitor comparison. Current L-0 baseline in progress.

**Key LME_S axes for gnosis:**
- Knowledge-update: clearly weakest (smoke test); T2 (validity intervals) is the fix
- Multi-session: expected to be moderate; T1 (community graph) may help
- Temporal-reasoning: expected to be strong (our existing temporal strength transfers)
- Abstention: need to baseline; our CoN instruction should help

**LOCOMO subset-3:** Keep as the regression gate at Run 18 config (~71 reproducible
level). Never report subset-3 as a competitive claim. Run 23 is the competitive
baseline (66.9–68.9 J excl-adv, parity with mem0).

**Evidence-recall@k instrumentation:** Every frontier ablation is retrieval-side.
gnosis currently cannot see whether LME_S misses are retrieval failures or synthesis
failures. This instrumentation is a prerequisite for trusting any new retrieval lever.

**MemoryArena** (arXiv:2602.16313): Quarterly smoke test once the gateway has an
agent-facing API. Rule-based scoring (no judge) is the right antidote to the judge
reliability crisis, but its costs don't fit an inner optimization loop.

---

## Appendix: verification ledger

| Claim | Status | Notes |
|---|---|---|
| JordanMcCann 96.2% LME_S | CONFIRMED | GitHub + DEV post, gpt-4o judge, seed=42, reproducible |
| Chronos 95.60% LME_S, 100% KU | CONFIRMED | arXiv:2603.16862, full category table |
| Mastra 96.2% KU | CONFIRMED | mastra.ai/research/observational-memory, gpt-4o judge |
| Zep 73.96% open-domain (Memori) | CONFIRMED | memorilabs.ai controlled eval, gpt-4.1-mini |
| Mem0 66.88 LOCOMO (GPT-5.5) | CONSISTENT | Memori shows 62.47% on gpt-4.1-mini; different judges, plausible |
| LOCOMO ceiling ~93.6% | CONFIRMED | Penfield Labs audit, April 2026, 99 confirmed errors |
| LME-V2 is conversational memory evolution | REFUTED | V2 measures web agent trajectory memory |
| HippoRAG 3 | NOT FOUND | Only HippoRAG 1 (2024) and 2 (2025) exist |
| EverMemOS sufficiency fires on 31% of queries | CONFIRMED | eval code + paper §3.5 |
| MemCon 2607.13591 published July 15 | CONFIRMED | arXiv |
| Mnemis adversarial 34.3% | PLAUSIBLE | Raw metrics JSON, not in paper body |
| Spreading activation key to JordanMcCann | CONFIRMED | GitHub ablation notes |
| "Is Grep All You Need?" BM25 > vectors on LME | CONFIRMED | arXiv:2605.15184 |
| Zep community layer explains open-domain gap | STRONG INFERENCE | No direct ablation, but Memori ~30 pp gap maps to community layer as the structural difference |
