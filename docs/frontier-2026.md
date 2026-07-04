# Agent-Memory Frontier, mid-2026: Dissection and Next Techniques for gnosis

*Compiled 2026-07-03. Deep-research pass over primary sources only (arXiv papers, official repos, raw
results JSON). Every load-bearing claim below was verified against the actual paper or code by fetching
it; anything we could not verify is flagged inline. Secondary sources (blogs, aggregators) are cited only
as critiques, never as evidence for a score.*

**Where gnosis stands (for reference):** LOCOMO subset-3, GPT-5.5 judge — context 59.5 / search 61.3 with
verbatim ingest; EMem-style extraction (edu-v1: dated, entity-normalized fact units) in measurement,
targeting 66–70. LLM recall filter tested flat (kept off). Relevance-ranked dated compact context
assembly. Graph QA exists but was off during benchmarks. Embeddings: local qwen3, 1024-dim. Strengths:
abstention/adversarial. Weaknesses: multi-hop, temporal.

---

## 0. Read this first: judge comparability

No number below is comparable to gnosis's GPT-5.5-judged scores. The frontier clusters as follows:

| Cluster | Systems (LOCOMO overall) | Caveats |
|---|---|---|
| **GPT-4.1-mini judge/backbone** | Mnemis 93.3 (k=10) / 93.9 (k=30); EverMemOS repo-companion 92.32; MemU 92.09; MemCog 92.98; True Memory 93.0; Mandol 92.21; H-Mem 92.01 | Roughly mutually comparable, but "backbone" (answer model) and "judge" are conflated differently per paper. MemU uses the *same* Azure gpt-4.1-mini deployment family as answerer and judge, with Mem0's explicitly "generous" grader prompt. All exclude the adversarial category. |
| **GPT-4o-mini judge/backbone** | Mnemis 89.8; EverMemOS paper 86.76 (86.76 is backbone; paper judge = GPT-4o-mini + two unnamed auxiliary judges averaged, κ>0.89 vs humans); Memory-R2 80.99 | The "~89.8 Mnemis" and "~81 Memory-R2" figures we tracked come from this cluster. Continua's "LoCoMo Fair Fight" measured **~10pp lift from switching the answer model gpt-4o-mini→gpt-4.1-mini alone** — so cross-cluster deltas of <10 points are noise. |
| **Other judges** | EverMemOS paper 93.05 (3-judge average); AtomMem 64.58 (deepseek-v4-pro judge); Memanto 87.1 (Claude Sonnet 4 + Gemini 3 judges); Mem0 "2026 algorithm" 92.5 (judge undisclosed — vendor blog) | Not comparable to anything else. |

**LOCOMO is at ceiling.** Independent audit (Penfield Labs, `github.com/dial481/locomo-audit` — pseudonymous,
but the audit data is public): **6.4% of gold answers are wrong** (99/1,540: hallucinated facts, temporal
errors, 24 speaker-attribution errors) ⇒ theoretical max ≈ **93.6**. The standard judge accepts
**62.8%** of intentionally-wrong-but-topical answers. The 92–94 frontier scores above are therefore
*at the ceiling*; differences among them are not meaningful. Zep's 84% famously collapsed to 58.44±0.20
under corrected protocol (`getzep/zep-papers` issue #5) — LOCOMO numbers swing ~25 points on protocol
alone. Two June-2026 meta-studies (MemDelta arXiv:2606.29914; "Are We Ready For An Agent-Native Memory
System?" arXiv:2606.24775) independently argue current LOCOMO/LongMemEval comparisons carry hidden
confounds and no architecture dominates.

**Implication for gnosis:** our absolute LOCOMO number is only meaningful against our own baselines under
our own GPT-5.5-judge harness. Chasing "92" is chasing a ceiling artifact; chasing our own
multi-hop/temporal deltas is real.

---

## 1. Mnemis (Microsoft) — dual-route retrieval on hierarchical graphs

- **Paper:** "Mnemis: Dual-Route Retrieval on Hierarchical Graphs for Long-Term LLM Memory",
  [arXiv:2602.15313](https://arxiv.org/abs/2602.15313) (v2 2026-04-10), stated accepted to ACL 2026
  (proceedings not yet checkable). Affiliation: "Microsoft" (Bing/M365-adjacent config strings in released
  metrics; *not* labeled Microsoft Research).
- **Repo:** [github.com/microsoft/Mnemis](https://github.com/microsoft/Mnemis), MIT. **Partial release
  only:** the System-2 `global_selection/` module (2 files), prompts, paper PDF, and raw results JSON.
  No ingestion pipeline, no System-1 code (delegated to Zep's Graphiti), no eval harness. Not
  independently runnable end-to-end.

**The two routes — key correction to what we believed:** there is **no escalation trigger**. System-1 and
System-2 run **in parallel on every query**; results are unioned and re-ranked by Qwen3-Reranker-8B
(RRF can't fuse across routes because System-2 output is unordered).

- **System-1 (fast):** embedding cosine search + BM25 full-text over Episodes / Entities / Edges (a
  Graphiti temporal graph on **neo4j** — same substrate as gnosis), merged with reciprocal rank fusion,
  re-ranked per type, truncated to budget. No caching.
- **System-2 (slow, "Global Selection"):** an LLM walks a **hierarchical category graph** top-down —
  categories are LLM-abstracted bottom-up from entities under three principles (minimum concept
  abstraction; **many-to-many parent mapping**, explicitly contrasted with GraphRAG's single-parent
  communities; compression-efficiency constraint). At the leaf layer it selects all relevant entities and
  pulls their connected episodes/edges — **no top-k limit**. Only cost control is early stopping when a
  whole branch is judged relevant. Yields output on 90.06% of queries. The hierarchical graph is
  **periodically rebuilt**, not incrementally maintained (stated future work).
- **Memory units:** Graphiti-style — Episodes (raw text, `valid_at`), Entities (name/summary/tag +
  embeddings), Edges ("verifiable statement… within a defined temporal or contextual scope", with
  `fact_embedding`, `valid_at`/`invalid_at`), episodic edges. Incremental LLM extraction with reflection
  + dedup; speakers force-extracted as entities.
- **Scores (judge = GPT-4.1-mini, official LoCoMo prompt, adversarial excluded "following common
  practice"):** GPT-4.1-mini backbone **93.3** (multi-hop 91.8 / temporal 90.3 / open-domain 82.3 /
  single-hop 96.2); k=30 → 93.9. GPT-4o-mini backbone **89.8**. Same-table baselines (4.1-mini):
  Full-context 80.6, EverMemOS 92.3, EMem-G 85.3, Zep 61.6, Mem0 66.3. LongMemEval-S: **91.6** vs
  EMem-G 84.9, EverMemOS 82.0. Per-category numbers independently recomputed from the repo's raw
  metrics JSON — they match exactly.
- **The number the paper doesn't surface:** the excluded adversarial category sits at **34.3%
  (153/446)** in the raw JSON. Mnemis is *bad* at exactly what gnosis is good at.
- **Cost/ablations:** no per-query latency published; whole-LoCoMo System-2 selection = 1.37M prompt
  tokens / 3,637 s (token-cheap, wall-clock slow). Ablation (overall, 4.1-mini): System-1 RAG 73.8 →
  +graph 89.1 → +System-2 **93.3** (System-2 alone 87.7, weakest on temporal 78.5). So the dual route is
  worth **+4.2 overall** and the gain "stems from global selection", not the reranker (reranker swap
  8B→0.6B costs ≤0.7).
- **Unverified:** per-route latency; adversarial vs baselines; ACL acceptance; any independent
  reproduction (impossible from released artifacts).

**Relevance to gnosis:** the strongest evidence in this whole survey that a *global/graph route unioned
with a vector route* buys multi-hop and temporal points on a neo4j substrate. Gnosis already owns the
substrate and a dormant graph-QA path.

---

## 2. EverMemOS — MemCells, scenes, and agentic retrieval

- **Paper:** "EverMemOS: A Self-Organizing Memory Operating System for Structured Long-Horizon
  Reasoning", [arXiv:2601.02163](https://arxiv.org/abs/2601.02163) (v2 2026-01-09). EverMind / Shanda
  Group (Lidong Bing among authors). Preprint; no confirmed venue.
- **Repo status — major caveat:** the paper's code URL now **redirects to
  [EverMind-AI/EverOS](https://github.com/EverMind-AI/EverOS)** (renamed ~2026-03/04), whose history was
  **rewritten (364 → 36 commits)** and whose architecture is different (SQLite+LanceDB local-first; thin
  MemCell = conversation slice). Current `CITATION.md` says "paper coming soon" and never cites its own
  arXiv paper. The paper-era Apache-2.0 code — including **all extraction prompts and the full 5-stage
  eval harness with baseline adapters** — survives only in forks
  ([tchen-coder/EverMemOS](https://github.com/tchen-coder/EverMemOS),
  [nightsailer/EverMemOS](https://github.com/nightsailer/EverMemOS)) and Wayback. Eval intermediates on HF:
  `EverMind-AI/EverMemOS_Eval_Results`.

- **MemCell (paper §3.2):** tuple **c = (E, F, P, M)** —
  - **E Episode:** "concise third-person narrative of the event, serving as the semantic anchor"
    (coreferences resolved);
  - **F Atomic Facts:** "discrete, verifiable statements derived from E for high-precision matching"
    (code field: `event_log`);
  - **P Foresight:** "forward-looking inferences (plans and temporary states) annotated with **validity
    intervals [t_start, t_end]**" (e.g. temporary 'flu' vs permanent 'graduation');
  - **M Metadata:** timestamps, source pointers.
  Actual Mongo model adds: `participants`, `subject`, `keywords`, `linked_entities`, `group_id`, raw
  `original_data`.
- **Creation:** LLM sliding-window **semantic boundary detection** segments the dialogue → narrative
  synthesis → constrained-schema derivation of facts + foresight.
- **Consolidation/linking — no knowledge graph.** MemCells are grouped into "MemScenes" by **incremental
  centroid clustering** (join nearest cluster if cosine ≥ τ [code default 0.65; paper 0.70 LoCoMo /
  0.50 LongMemEval] AND within a time gap [7d LoCoMo / 30d LongMemEval]); scene summaries and a **user
  profile** (explicit facts + implicit traits, recency-aware, conflict-tracked) are refreshed online.
  Clustering itself costs zero LLM tokens. Foresight records are stored separately with vectors and
  parent pointers. No LLM-based merge of cells.
- **Retrieval (§3.5 + App. A.1, corroborated in eval code):**
  1. **Hybrid dense (Qwen3-Embedding-4B/Milvus) + BM25 (Elasticsearch), RRF k=60, over Atomic Facts**;
  2. scene selection: score scene by **max relevance of member cells**, top-10 scenes;
  3. **Qwen3-Reranker-4B over the pooled Episodes**, top-10;
  4. **date filter**: foresight kept only if `t_now ∈ [t_start, t_end]`;
  5. **agentic sufficiency check** (strict-JSON prompt that explicitly decomposes temporal requirements —
     before/after/since/during); if insufficient, generate **2–3 complementary queries** (entity pivot,
     temporal calculation anchored on document dates, concept expansion, constraint relaxation; keyword /
     natural-question / **HyDE** styles), fuse via multi-query RRF. **Fires on 31.0% of LoCoMo
     questions.** A no-LLM "fast mode" (pure BM25) exists.
- **Scores:** two sets. Paper Table 1 (3-judge average incl. GPT-4o-mini): **93.05** overall
  (single-hop 96.67 / multi-hop 91.84 / temporal 89.72 / open-domain 76.04) vs Zep 85.22, MemOS 80.76,
  MemU 66.67(!) under aligned protocol. Repo companion (gpt-4.1-mini): **92.32** — this is the "~92.3" we
  tracked. Full-context baseline in their own table: 91.21 — i.e., EverMemOS beats full-context by ~1–2
  points on a saturated benchmark. LongMemEval-S: **82.00–83.00** (baselines copied from the MemOS
  leaderboard, not re-run — comparability caveat), with knowledge-update 89.74 its standout.
- **Unverified:** identity of the two auxiliary judges; reproducibility from official main (impossible —
  harness gone); why history was rewritten.

**Relevance to gnosis:** the most complete, prompt-included blueprint of a frontier retrieval stack:
facts-for-matching + episodes-for-context (multi-granularity), hybrid+RRF, local Qwen3 reranker,
validity-interval time filtering, and a bounded sufficiency/rewrite loop. Everything maps onto our
existing verbatim-ingest + fact-unit design.

---

## 3. MemU (NevaMind-AI) — organizational novelty, vendor-grade evidence

- **No paper exists** (arXiv search returns nothing; launch Medium post is HTTP 410).
  **Repo:** [NevaMind-AI/memU](https://github.com/NevaMind-AI/memU), Apache-2.0, ~14.0k stars, very
  active. Eval: [NevaMind-AI/memU-experiment](https://github.com/NevaMind-AI/memU-experiment) — a
  one-day frozen snapshot (created and last pushed 2025-11-21) with full `result.json`.
- **Architecture (current v1.5):** atomic unit = `RecallEntry` — **free-text single-sentence summary**
  typed as profile/event/knowledge/behavior/skill/tool, optional embedding, optional `happened_at`
  (only added v1.3.0, Jan 2026 — *after* the benchmark), SHA-256-of-normalized-text dedup with
  reinforcement counts. Entries grouped into `RecallFile` category/skill files with their own summaries
  and embeddings; exported as an LLM-navigable Markdown tree (`INDEX.md` / `MEMORY.md` / `SKILL.md`).
  Retrieval: staged **intention routing / query rewrite → category files → entries → raw resources**
  with per-stage LLM sufficiency "judger" early stopping; `rag` (embedding) or `llm` (LLM-as-ranker)
  strategies.
- **Vs EMem-style units:** representationally *weaker* — undated (at benchmark time), un-normalized
  prose; paraphrase duplicates; dedup stage is an acknowledged pass-through placeholder. The genuine
  novelty is **organizational**: category-file hierarchy with summary-level routing down to raw sources,
  and the skill track distilled from tool traces.
- **The 92.09 claim, dissected from their own `result.json`:** 1420/1542 with **adversarial excluded**
  (1,986 total questions); Azure **gpt-4.1-mini as both answerer and judge** (same configurable client
  class), Mem0's verbatim "be generous with your grading" prompt, character profile injected into the
  answer prompt. Per-category: multi-hop 88.3 / temporal 92.5 / open-domain 77.1 / single-hop 94.9 /
  adversarial 2-of-2-sampled. Their own experiment README shows a conflicting adversarial-included
  "Overall: 88.31%". The benchmarked system is the **deprecated 2025 architecture** (memory-agent +
  per-character markdown files + theory-of-mind pass), not the current pip package; no re-run published;
  **zero third-party reproductions found**. Under EverMemOS's aligned harness, MemU scores **66.67**
  LoCoMo / **38.40** LongMemEval — a 25-point gap vs its self-report.
- **Verdict:** vendor-reported with unusually transparent artifacts, but *not* frontier-comparable
  evidence. Per our own rule (no single unverifiable vendor claim), MemU contributes **no technique
  recommendation on its own**; its staged category→entry→resource retrieval only counts as corroboration
  where it overlaps EverMemOS/Mnemis patterns.

---

## 4. Memory-R2 — RL-trained extraction with a 7B model

- **Paper:** "Memory-R2: Fair Credit Assignment for Long-Horizon Memory-Augmented LLM Agents",
  [arXiv:2605.21768](https://arxiv.org/abs/2605.21768) (2026-05-20). LMU Munich / MCML / Huawei
  Heisenberg / TUM; direct follow-up to Memory-R1 (arXiv:2508.19828) by an overlapping team. Preprint,
  no venue. **Code:** [ahmedehabb/Memory-R2](https://github.com/ahmedehabb/Memory-R2) (Apache-2.0,
  VERL-based, curriculum scripts, LoCoMo pipeline). **No checkpoints released** (HF search empty;
  README references only local paths) — you must train your own.
- **Setup:** ONE shared **Qwen2.5-7B-Instruct** plays both **fact extractor** and **memory manager**
  (INSERT/UPDATE/DELETE) via role prompts, alternating chunk-wise per session. Answer agent **frozen
  during memory training** (GPT-OSS-120B) to keep reward clean.
- **Algorithm — LoGo-GRPO:** standard GRPO is "fundamentally unfair" once rollouts diverge in memory
  state, so a **global branch** (16 trajectory-level rollouts) is combined with a **local branch** that
  re-rolls sampled sessions *from shared cached intermediate memory states* for fair session-level credit.
  Curriculum 8→16→32 sessions (direct 32-session training collapses F1 0.47→0.27).
- **Reward — judge-free:** `R = mean token-F1 of frozen answer agent on that session's attributed QA
  pairs − λ·(memory-bank tokens over budget)`. No LLM judge anywhere in training.
- **Training data:** shockingly small — **2 LoCoMo conversations, 328 QA pairs** (2:1:7 split).
- **Results (judge = gpt-4o-mini, binary; 7 held-out conversations; backbone-controlled — all baselines
  also on Qwen2.5-7B):** Memory-R2 all-7B **F1 50.60 / Judge 80.99** (multi-hop J 80.93, temporal J
  69.90) vs Memory-R1 43.14/61.51, Mem0 30.61/53.30, MemAgent 40.72/71.52. With 120B answer agent:
  J 87.10 but *lower* F1 than all-7B. OOD transfer: LongMemEval-oracle F1 27.88→50.60. Scales down:
  Qwen2.5-3B 10.3→46.8 F1.
- **Ablations on extraction vs scale (the question we asked):** no direct "RL-7B extractor vs prompted
  GPT-4o extractor" table exists. What is shown: (a) **prompted 7B memory module + 120B answer agent =
  30.6 F1 vs RL-trained 7B memory module ≈ 49.7 F1 regardless of answer agent** — "the dominant gain
  comes from training the memory module… varying the answer agent at fixed RL-trained memory yields
  comparably high scores" (Fig. 2c); (b) training only the manager −4.3 F1, training **only the
  extractor −21.4 F1** with M-Fail 56.5% — "fact extraction is the more brittle of the two roles when
  left untrained."
- **Unverified:** exact λ/α hyperparameter values (~0.3 unconfirmed); chunk count of the full system;
  any extractor-scale head-to-head.

**Relevance to gnosis:** strongest evidence anywhere that **extraction quality dominates backbone scale**
— which validates the current edu-v1 extraction investment — and a credible medium-term path to a local
RL-tuned extractor. But with no released checkpoints and a gpt-4o-mini judge, it's a research direction,
not a drop-in.

---

## 5. MemoryArena — what post-LOCOMO evaluation looks like

- **Paper:** "MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks",
  [arXiv:2602.16313](https://arxiv.org/abs/2602.16313) (2026-02-18). Stanford/UCSD/UIUC/Princeton/
  Pitt/2077AI (He, Wang, … McAuley, Choi, Pentland). **Repo:**
  [ZexueHe/MemoryArena](https://github.com/ZexueHe/MemoryArena) (self-described preview);
  dataset on HF (CC-BY-4.0, ~12 MB). No public leaderboard.
- **What it measures differently:** memorization and *action* coupled — 766 human-crafted tasks with
  **interdependent subtasks** across grounded environments (WebShop-style bundled shopping, group travel
  planning, progressive web search, formal reasoning), avg 6.9 subtasks / ~57 action steps / >40k-token
  traces, where "later actions are underspecified unless agents correctly track task-relevant
  information from prior sessions." **Metrics are rule-based success/progress — no LLM judge at all.**
- **Headline finding:** everything fails. Avg Success Rate ~0.16 (GPT-5.1-mini backbone): Letta 0.15,
  Mem0 0.14, Mem0-graph 0.12, ReasoningBank 0.12 — **memory agents lose to plain RAG (BM25 0.19,
  dense 0.23) and to long-context**, while also being 1.5–4x slower. Group travel: SR 0.00 for every
  method class. The LOCOMO-saturation argument is qualitative ("agents with near-saturated performance
  on existing long-context memory benchmarks like LoCoMo perform poorly in our agentic setting") — no
  side-by-side score table.
- **Adoption assessment for membench:** the harness is public, modular (`agent/`, `env/`, `memory/`
  client abstraction — where a gnosis backend would plug in), but requires standing up interactive
  environment servers and is far heavier than QA benchmarks (34–133 s/subtask). Dataset/paper count
  mismatch (701 HF rows vs 766 claimed) unexplained.
- **Recommendation:** **adopt LongMemEval_S first** (temporal reasoning, knowledge updates, multi-session
  categories map directly to our weaknesses; QA-shaped; cheap; also now has LongMemEval-V2,
  arXiv:2605.12493). Treat MemoryArena as a **quarterly smoke test, not a tuning target**: run one subset
  (Progressive Web Search is closest to memory-retrieval skill) once the gnosis gateway has an
  agent-facing API. Its rule-based scoring is the antidote to every judge problem documented above, but
  its costs don't fit an inner optimization loop.

---

## 6. May–July 2026 sweep (verified paper/repo only)

| System | Source | LOCOMO / LongMemEval | Judge | Mechanism in one line | OSS |
|---|---|---|---|---|---|
| **MemCog** | [arXiv:2605.28046](https://arxiv.org/abs/2605.28046) (May 27) | 92.98 / 95.8 | 4.1-mini / GPT-4o | "Memory-as-cognition": agentic **ReAct loop navigating an associative memory graph**, reasoning interleaved with retrieval | benchmark only (anonymized) |
| **True Memory** | [arXiv:2605.04897](https://arxiv.org/abs/2605.04897) (May 6) | 93.0 / 87.8 | 4.1-mini | **Verbatim events, zero ingestion-time extraction**, six-layer answer-time retrieval; single SQLite file, CPU-only; claims accuracy-per-cost, not #1 (their own EverMemOS re-run: 94.5) | not stated |
| **Mandol** | [arXiv:2606.29778](https://arxiv.org/html/2606.29778) (Jun 29) | 92.21 / 88.40 | 4.1-mini | Two-layer semantic graph; **BM25 + SPLADE + dense hybrid**, selective subgraph expansion for multi-hop, MAD-threshold denoising, MMR packing; 5.4x retrieval speedup | [AgentCombo/Mandol](https://github.com/AgentCombo/Mandol) |
| **H-Mem** | [arXiv:2605.15701](https://arxiv.org/html/2605.15701v1) (May 15) | 92.01 / 89.20 (LME_S) | 4.1-mini | **Temporal-semantic tree** (time windows × granularity) + KG for multi-hop traversal; ranking fuses semantic + temporal + forgetting-curve scores; claims biggest gains on multi-hop/temporal | no repo |
| **AtomMem** | [arXiv:2606.19847](https://arxiv.org/abs/2606.19847) (Jun 18) | 64.58 (deepseek-v4-pro judge — **not comparable**) | dsv4 | Atomic facts + temporal user-attribute profiles; **Random-Walk-with-Restart activation over entity/event/temporal edges** | [MINE-USTC/AtomMem](https://github.com/MINE-USTC/AtomMem) |
| **MemForest** | [arXiv:2605.23986](https://arxiv.org/abs/2605.23986) (May 16) | — / 79.8 pass@1 | unstated | Write-efficient temporal tree index; ~6x construction throughput vs EverMemOS (efficiency SOTA, not accuracy) | not stated |
| **TSM** (Jan, ACL Findings '26 — context) | [arXiv:2601.07468](https://arxiv.org/abs/2601.07468) | +12.2 abs on temporal splits | — | **Occurrence-time semantic timeline** (event time ≠ mention time), durative-memory consolidation, temporal query-intent interpretation | — |
| Mem0 "2026 algorithm" | [vendor blog](https://mem0.ai/blog/state-of-ai-agent-memory-2026) | 92.5 / 94.4 | **undisclosed** | 3 parallel scoring passes (semantic/keyword/entity) fused | — |

Excluded for failing verification: HyperMem (only exists as a row in MemCog's tables), omegamax
leaderboard "94.6" (unattributed aggregator), ZenBrain/Hippocampus/OmniMem etc. (no primary-source
scores). Benchmark-side: **LongMemEval-V2** ([arXiv:2605.12493](https://arxiv.org/abs/2605.12493)) is
where SOTA claims will migrate next.

---

## 7. Techniques appearing in ≥2 verified frontier systems (that gnosis hasn't tried)

1. **Hybrid sparse+dense retrieval fused with RRF** — Mnemis (BM25+embedding, RRF), EverMemOS (BM25+
   dense, RRF k=60 over atomic facts), Mandol (BM25+SPLADE+dense), Mem0-2026 (semantic+keyword+entity).
   Gnosis is dense-only (qwen3).
2. **Local cross-encoder reranking** — Mnemis (Qwen3-Reranker-8B; ablation shows 0.6B costs ≤0.7 pts),
   EverMemOS (Qwen3-Reranker-4B). Fits our local-qwen3 stack exactly.
3. **Sufficiency-check → multi-query rewrite loop** (bounded agentic retrieval) — EverMemOS (fires 31%,
   strategies incl. *temporal calculation* and *entity pivot*), MemCog (full ReAct navigation), MemU
   (staged sufficiency judgers — vendor-grade corroboration only). NB: this is *generative expansion*,
   not the *discriminative* LLM recall filter we measured flat.
4. **Temporal validity intervals + answer-time date filtering + temporal query decomposition** —
   EverMemOS (foresight [t_start,t_end] + date filter + temporal sufficiency decomposition), Mnemis
   (`valid_at`/`invalid_at` on edges), TSM (occurrence-time timeline), H-Mem (temporal-semantic tree).
5. **A global/graph route run in parallel with the vector route** — Mnemis (System-2, +4.2 overall;
   ablation attributes the gain to global selection), Mandol (subgraph expansion), H-Mem (KG traversal),
   AtomMem (RWR). Distinctly *answer-time reasoning over structure*, not ingest-time structure alone.
6. **Multi-granularity: match on atomic facts, assemble context from episodes/verbatim** — EverMemOS
   (facts → scene → episode rerank), True Memory (verbatim events + heavy answer-time retrieval), MemU
   (entries → raw resources; vendor-grade), Memanto (high-recall chunk dump + in-context reasoning).

---

## 8. Ranked next techniques for gnosis (max 6)

Scoring lens: our weak categories are multi-hop and temporal; our judge is GPT-5.5 (nothing external is
comparable); membench measures per-category deltas on LOCOMO subset-3 today, LongMemEval_S next.

### T1. Hybrid BM25 + dense with RRF, + local Qwen3 reranker
- **Mechanism:** add a Neo4j full-text (Lucene/BM25) index over fact units and verbatim turns; run it
  beside qwen3 dense search; fuse with RRF (k=60 per EverMemOS); optionally cap with
  Qwen3-Reranker-0.6B/4B (local, fits our stack) before context assembly.
- **Evidence:** peer-reviewed-track (Mnemis/ACL'26 ablation: RAG 73.8 → +graph+fusion 89.1; reranker
  size barely matters) + preprint (EverMemOS, exact recipe with prompts) + preprint (Mandol). Strongest
  multi-source evidence of anything on this list.
- **Expected gain:** broad; multi-hop benefits most (entity-name exact matches that 1024-dim dense misses
  are classic multi-hop bridge failures). Low risk to abstention strength (retrieval-side only).
- **Cost:** **low** — Neo4j full-text indexes are built-in (`db.index.fulltext.*`); RRF is ~20 lines;
  reranker is one local model call. Days, not weeks.
- **membench:** A/B on subset-3 search mode, per-category; plus a retrieval-recall@k metric against gold
  evidence turns (we should add evidence-recall instrumentation regardless — every frontier ablation
  is retrieval-side).

### T2. Temporal query decomposition + validity-window filtering at answer time
- **Mechanism:** (a) parse the query's temporal intent (before/after/since/during/at-time-X — EverMemOS's
  sufficiency prompt does this in strict JSON) and rewrite relative expressions against session dates;
  (b) since our facts are already dated, add `valid_from/valid_to` semantics for stateful facts
  (jobs, locations, plans — EverMemOS "foresight" intervals; Mnemis `valid_at`/`invalid_at`) and
  hard-filter/boost candidates whose window matches the query's target time; (c) rank by occurrence time,
  not mention time (TSM's core finding, +12.2 abs on temporal splits).
- **Evidence:** preprint ×3 with one ACL-Findings (TSM); mechanism-level convergence across four systems.
- **Expected gain:** **largest targeted temporal gain available.** Frontier temporal scores (89.7–92.5)
  vs typical baseline temporal is the single widest category gap in every table we verified.
- **Cost:** **medium** — schema touch (interval fields on fact units), one extraction-prompt extension
  (edu-v2), one query-analysis LLM call, Cypher filter changes.
- **membench:** LOCOMO temporal-category delta; then LongMemEval_S temporal-reasoning and
  knowledge-update categories (the latter is exactly interval-invalidations done right).

### T3. Re-enable graph QA as a parallel global route, unioned before rerank (Mnemis dual-route)
- **Mechanism:** don't gate or escalate — run the existing gnosis graph-QA path on **every** query in
  parallel with vector search; union candidates; rerank jointly (T1's reranker resolves the
  unordered-vs-ranked fusion problem exactly as Mnemis does). Optionally add a cheap Mnemis-style
  category/community layer later; start with what we have (entity-neighborhood expansion from matched
  fact units).
- **Evidence:** peer-reviewed-track (Mnemis ablation: +4.2 overall from System-2; System-2-only already
  87.7; gain attributed to global selection, not reranking) + Mandol/H-Mem/AtomMem convergence on
  answer-time graph reasoning for multi-hop.
- **Expected gain:** multi-hop primarily (Mnemis multi-hop 91.8 with vs ~89 without System-2; AtomMem/
  H-Mem both motivate graph traversal specifically for multi-hop). Temporal secondary — note Mnemis's
  System-2 alone is *weakest* on temporal, so T2 is the temporal play, not this.
- **Cost:** **low-medium** — the code exists and was merely off; the new work is union+rerank plumbing
  and latency budgeting (Mnemis's System-2 is token-cheap but wall-clock slow; ours is a bounded Cypher
  expansion, cheaper).
- **membench:** three-arm run: vector-only / graph-only / unioned+reranked, per-category. Also track
  answer latency per arm.

### T4. Bounded sufficiency-check + multi-query rewrite loop (max 1 extra round)
- **Mechanism:** after first retrieval, one strict-JSON LLM verdict: sufficient? If not, emit 2–3
  complementary queries — entity pivot (multi-hop bridges), temporal calculation, concept expansion,
  HyDE-style statement — retrieve, fuse all rounds with multi-query RRF. Hard cap at one extra round
  (EverMemOS shows it fires on only 31% of questions, bounding cost).
- **Evidence:** preprint ×2 (EverMemOS with published prompts; MemCog's ReAct navigation is the
  maximalist version and posts the sweep's best LongMemEval). Important distinction from our flat
  result: our LLM recall filter *discarded* candidates (precision play); this *adds* reformulated
  queries (recall play) — the frontier evidence is on the recall side.
- **Expected gain:** multi-hop (entity pivot is literally hop-2 lookup) and temporal (anchored date
  arithmetic) — both our weak categories.
- **Cost:** **medium** — one prompt + loop in the search path; +1 LLM call on ~30% of queries; latency
  budget must be watched. Build after T1 (fusion machinery is shared).
- **membench:** per-category deltas + fire-rate + tokens/query + p95 latency; verify abstention/
  adversarial does not regress (extra retrieval rounds can manufacture false support — our adversarial
  strength is worth protecting; note Mnemis's 34.3% adversarial as a cautionary tale for aggressive
  retrieval).

### T5. Multi-granularity assembly: match on facts, expand to verbatim episode context
- **Mechanism:** we already store verbatim turns and fact units — link each fact to its source span;
  at answer time, retrieve/rank on fact units (precision) but assemble the context window from the
  parent verbatim turn-pairs/episode around top facts (recovering nuance that atomization destroys),
  within the existing compact-context token budget.
- **Evidence:** preprint ×2+ (EverMemOS facts→episodes rerank; True Memory's whole thesis — verbatim +
  answer-time retrieval hits 93.0; Memanto's high-recall dump; MemU entry→resource as vendor-grade
  corroboration). Also consistent with our own data: verbatim-ingest search (61.3) is respectable, so
  the raw text carries answerable signal our fact units may be dropping.
- **Expected gain:** temporal and open-domain nuance (relative-time phrases like "last weekend" survive
  in verbatim); moderate multi-hop.
- **Cost:** **low** — provenance links likely exist from ingest; this is a context-assembly change only,
  no schema/model work.
- **membench:** context-mode A/B: facts-only vs facts+parent-verbatim at equal token budget, per-category.

### T6 (watch, not build): RL-tuned local extractor (Memory-R2 recipe)
- **Mechanism:** GRPO-style outcome-reward tuning (judge-free token-F1 of a frozen answerer − compression
  penalty) of a small local extractor+manager over our own ingest format; code is Apache-2.0
  (VERL-based), checkpoints are NOT released.
- **Evidence:** preprint ×1 (single system — flagged per our rule; kept only because the code is public
  and ablations are internal-consistent, and it *validates* rather than redirects our extraction bet:
  untrained extraction −21.4 F1 is the most brittle component; trained 7B memory module beats prompted
  module + 120B answerer).
- **Expected gain:** potentially large and durable (extraction quality dominates scale) but unproven off
  LoCoMo-style data; risk of benchmark overfit (trained on 2 conversations from the same distribution).
- **Cost:** **high** — GPU training pipeline, reward plumbing into membench, weeks. Revisit after T1–T5
  and after edu-v1 numbers land.
- **membench:** if ever built, the reward *is* membench (frozen answerer F1) — natural fit; evaluate on
  held-out subset + LongMemEval_S OOD to check transfer, mirroring the paper's OOD protocol.

**Explicit non-recommendations:** MemU's architecture on its own evidence (vendor-only, deprecated-code
benchmark, same-family judge, 25-pt gap under aligned re-eval); chasing LOCOMO ≥92 (ceiling artifact,
§0); Mnemis-style full hierarchical-category rebuild (periodic full rebuilds don't fit a live gateway;
revisit only if T3's simple graph route plateaus); adopting MemoryArena as a tuning target (use as
quarterly smoke test only, §5).

### Benchmark posture
Adopt **LongMemEval_S** now (its temporal-reasoning, knowledge-update, and multi-session categories are
purpose-built for our weaknesses, and 500 curated questions with a documented judge beat LOCOMO's broken
answer key). Keep LOCOMO subset-3 for continuity but report per-category only, never overall. Add
evidence-recall@k instrumentation to membench (every frontier ablation is retrieval-side; we currently
can't see whether misses are retrieval or synthesis). MemoryArena: quarterly smoke test once the gateway
exposes an agent-facing API.

---

## Appendix: verification ledger (what we could NOT verify)

- **Mnemis:** per-route latency (not reported); ACL'26 proceedings entry (not yet published); any
  independent reproduction (System-1/ingest/eval code withheld). The ~89.8 we tracked = GPT-4o-mini
  backbone row, not the headline.
- **EverMemOS:** identities of 2 of 3 judges; motive for repo history rewrite; reproducibility from
  official main (paper code survives only in forks). The ~92.3 we tracked = OSS-companion run, paper
  headline is 93.05.
- **MemU:** no paper; no third-party reproduction; benchmark ran on deprecated architecture;
  memu.pro/benchmark page unreadable (403); conflicting 88.31% figure in their own README.
- **Memory-R2:** no released checkpoints anywhere; no direct extractor-scale head-to-head (the
  scale-vs-training claim is indirect via Fig. 2c/Table 2); λ/α values unconfirmed.
- **MemoryArena:** no leaderboard; no in-paper LOCOMO-vs-Arena score table (saturation argument is
  qualitative); 701-vs-766 task-count mismatch; per-cell table values extracted via HTML summarization —
  re-check against PDF before quoting formally.
- **LOCOMO audit:** author pseudonymous ("dial481"/Penfield Labs); data public but methodology not
  peer-reviewed.
- **Sweep:** Mem0-2026 judge undisclosed (vendor blog); MemCog LongMemEval variant not explicitly
  labeled _S; MemForest judge unstated; HyperMem primary source never located.
