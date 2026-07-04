# Literature gaps: abstention calibration & long-horizon memory maintenance

Targeted research (2024–2026, primary sources where possible) on two gaps in our coverage.
Context: gnosis scores LOCOMO 71.2 J (excl. adversarial) with extraction, but (a) the
adversarial/abstention score dropped 74.1 → 67.9 as retrieval got richer, and (b) nothing we
have built or measured addresses long-horizon maintenance (membench ingests once and asks
immediately).

---

## Gap 1 — Answerability calibration / selective answering for memory-augmented QA

### The core phenomenon is documented: richer retrieval degrades abstention

Google's **"Sufficient Context: A New Lens on Retrieval Augmented Generation"**
([arXiv:2411.06037](https://arxiv.org/pdf/2411.06037), + [research.google blog](https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/))
directly explains our 74.1 → 67.9 drop: adding context makes models *more confident and less
likely to abstain*, even when the context is insufficient. Measured: Gemma's incorrect-answer
rate rose from 10.2% (no context) to 66.1% (insufficient context). The effect is a property of
the answer model, not the retriever. Their fixes:

- **Sufficient-context autorater**: an LLM classifier judging "does the retrieved context fully
  determine the answer?" — ≥93% agreement with human experts (n=115), best with a strong
  prompted model (no fine-tuning needed).
- **Selective generation**: combine autorater label + model self-confidence to decide abstention
  → up to **2–10% improvement in selective accuracy** over confidence alone.

Supporting literature:

- **AbstentionBench** ([arXiv:2506.09038](https://arxiv.org/html/2506.09038v1)): frontier and
  *reasoning* LLMs systematically fail on unanswerable questions (reasoning fine-tuning makes it
  worse, −24% avg); but an **explicit abstention system prompt boosts abstention rates without
  significant loss of abstention precision** — cheap and measured.
- Grounded-generation prompting (answer only from cited evidence, else decline): a domain RAG
  benchmark ([arXiv:2606.24725](https://arxiv.org/pdf/2606.24725)) measured **abstention
  accuracy 1.0 on unsupported queries** when the prompt required evidence grounding — small-n
  domain study, weak-moderate evidence, but consistent with AbstentionBench.
- Retrieval-score-based abstention (abstain if top-k relevance scores fall below a threshold)
  appears in surveys and pipelines ([RAG robustness survey, arXiv:2506.00054](https://arxiv.org/html/2506.00054v1);
  [counterfactual-prompting risk control, arXiv:2409.16146](https://arxiv.org/html/2409.16146v1);
  ["Trust or Abstain? Self-Aware RAG", arXiv:2605.18792](https://arxiv.org/pdf/2605.18792)),
  but the Merlin-Arthur RAG paper ([arXiv:2512.11614](https://arxiv.org/html/2512.11614)) notes
  uncertainty/score calibration for abstention "remains unreliable" — weakest of the three
  families. RL-based approaches (GRACE [arXiv:2601.04525](https://arxiv.org/pdf/2601.04525),
  Abstain-R1 [arXiv:2604.17073](https://arxiv.org/html/2604.17073)) require training — out of
  scope for gnosis.

### What frontier memory systems do: mostly nothing

- **Mnemis** ([arXiv:2602.15313](https://arxiv.org/pdf/2602.15313)): the paper *excludes* the
  LoCoMo adversarial category from headline results, following field practice (Mem0, Zep,
  Memobase, Hindsight all exclude it). The 34.3 figure could not be verified in the paper
  itself — treat it as secondary/self-reported-adjacent. Either way: no abstention mechanism
  described.
- **LongMemEval** ([arXiv:2410.10813](https://arxiv.org/html/2410.10813v2)): defines the
  30-question abstention (`_abs`, false-premise) category but its optimizations (session
  decomposition, fact-augmented keys, time-aware query expansion, Chain-of-Note reading) target
  recall, not abstention; no abstention-specific technique or per-category SOTA breakdown.
  Third-party runs ([Memoria/MatrixOrigin](https://medium.com/@matrixorigin-database/benchmarking-memoria-on-longmemeval-strong-memory-retrieval-clear-reader-separation-ee6c89c75d76))
  show abstention is mostly a **reader property**: claude-opus-4.6 93.3% vs gpt-5.4 56.7% on
  identical retrieved memories.
- **Synthius-Mem** ([arXiv:2604.11563](https://arxiv.org/pdf/2604.11563)) claims 99.6% LoCoMo
  adversarial robustness via structured persona facts + CategoryRAG — self-reported, mechanism
  not isolated, no independent replication (weak evidence). Notable that its answers are
  constrained to structured extracted facts, i.e. evidence grounding at the schema level.

### Ranked implementable techniques

1. **Evidence-grounded abstention prompt** (strongest evidence: AbstentionBench +
   grounded-generation studies; near-zero cost). Reader prompt requires: cite the specific
   memory ID(s) supporting the answer; if no retrieved memory entails the answer, output
   "I don't know"; if the question presupposes an event not in memory, say so.
   *Gnosis:* prompt change only. *Membench:* LOCOMO adversarial (n=112) abstention accuracy +
   answerable-category accuracy (watch for over-abstention regression), plus LongMemEval_S
   `_abs` subset (n=30).
2. **Cheap answerability/sufficiency check** (strong evidence: Google 2411.06037, 93% autorater
   accuracy, +2–10% selective accuracy). One extra small-model call: "Given retrieved memories
   M and question Q, is Q fully answerable from M? yes/no." Abstain on "no" unless model
   confidence is high. *Gnosis:* gateway-side pre-answer step (haiku-class model, ~1 cheap
   call/query). *Membench:* same subsets; also report coverage (fraction answered) so the
   accuracy/abstention trade-off is visible.
3. **Retrieval-score-distribution threshold** (weakest evidence; calibration known to be
   unreliable, but free). Abstain or down-weight when max/mean top-k similarity falls below a
   threshold tuned on a held-out split. *Gnosis:* retrieval-stage flag passed to the reader
   ("evidence is weak"). Use as a supplementary signal to #2, not standalone. *Membench:* sweep
   the threshold, plot abstention accuracy vs answerable accuracy (risk–coverage curve).

**Caveats:** LongMemEval abstention n=30 and LOCOMO adversarial n=112 are small — report exact
counts; differences under ~8–10 points on the LongMemEval subset are noise. The Memoria result
implies the biggest single lever may simply be which reader model answers; measure per-reader
before crediting any pipeline change.

---

## Gap 2 — Long-horizon memory maintenance: measured evidence

### Evidence that maintenance affects end-task accuracy

**Strong (peer-benchmark, measured):**

- **Deterministic conflict resolution beats LLM-side freshness tracking.**
  ["Don't Ask the LLM to Track Freshness"](https://arxiv.org/html/2606.01435v1)
  (arXiv:2606.01435): a 3-step pipeline (BM25 top-10 → LLM candidate match → deterministic
  `max(serial_number)`) hits **78.0%/94.8%** (gpt-4o-mini/gpt-4o) on MemoryAgentBench
  FactConsolidation single-hop vs **54.0%** for HippoRAG-v2 — and **Zep, with its bi-temporal
  invalidation edges, scores only 7.0%** on the same task. The gap widens with context length
  (+8pp at 6K tokens → +21pp at 262K). Takeaway: architecture complexity ≠ conflict resolution;
  a deterministic "newest wins" aggregation step does the work.
- **Add-all accumulation measurably degrades performance; selective add + deletion helps.**
  [Experience-following study](https://arxiv.org/html/2505.16067v2) (arXiv:2505.16067): add-all
  drops success 67.5% → **55.5%** as memory grows to 4,100 entries; selective addition with a
  strict evaluator reaches **71%**; history-based deletion improves performance while shrinking
  memory 22%; periodic deletion cuts memory 67% with minimal loss. Noisy stored records
  compound downstream mistakes.
- **The supersession gap doesn't fix itself with scale or capacity.**
  [Supersede](https://arxiv.org/html/2606.27472) (arXiv:2606.27472): bounded self-maintained
  memory drops GPT-5.4 from 92% → 77% vs full context; 24× longer conversations drop accuracy
  68% → 28%, and 24× more memory recovers **nothing** (28% → 28%). Only training (GRPO on a
  supersession environment) helped in their tests.
- **ADD-only can beat UPDATE/DELETE on some categories.** Mem0's newer results
  ([mem0 research](https://mem0.ai/research-3), **vendor self-reported**) credit an ADD-only
  architecture with large temporal-reasoning gains (+42.1 per
  [third-party writeup](https://www.byterover.dev/blog/benchmark-ai-agent-memory)) because
  destructive UPDATE/DELETE erases chronological context. Consistent with 2606.01435: **keep
  history append-only, resolve recency deterministically at read time** — destructive
  write-time editing loses information.

**Weak (vendor / safety-adjacent):**

- Zep's DMR 94.8% and LongMemEval +18.5% ([arXiv:2501.13956](https://arxiv.org/pdf/2501.13956))
  are self-reported and, per the FactConsolidation result above, do not translate into
  conflict-resolution ability.
- [MemEvoBench](https://arxiv.org/abs/2604.15774) and
  [longitudinal safety risks](https://arxiv.org/html/2605.17830v1) show accumulated
  misleading/contaminated memories cause behavioral drift;
  [Vending-Bench](https://arxiv.org/pdf/2502.15840) shows degradation continues long after
  memory is "full." Evidence of the failure mode, not of a fix.

### SOTA on LongMemEval knowledge-update

- **Mastra Observational Memory: 96.2%** (gpt-5-mini; 85.9% gpt-4o) — credits *temporal
  anchoring* (observed / referenced / relative dates per observation) plus a *Reflector* that
  periodically consolidates and removes superseded observations
  ([Mastra research](https://mastra.ai/research/observational-memory), vendor self-reported).
- **Chronos: 96.15%** vs Honcho 94.87% ([arXiv:2603.16862](https://arxiv.org/pdf/2603.16862)) —
  structured event retrieval with temporal awareness.
- **Memanto: 93.6%** ([arXiv:2604.22085](https://arxiv.org/pdf/2604.22085)).
- Reader matters a lot: with an identical retrieval snapshot, knowledge-update ranged
  **58.4%–89.6%** across reader models
  ([Memoria/MatrixOrigin](https://medium.com/@matrixorigin-database/benchmarking-memoria-on-longmemeval-strong-memory-retrieval-clear-reader-separation-ee6c89c75d76))
  — the evidence is usually retrieved; models fail at *choosing the latest valid fact*. Common
  failure: overwrite/compression of older facts during consolidation.

Mechanisms SOTA systems actually credit: (a) every fact timestamped with both event time and
observation time, (b) read-time or consolidation-time preference for the latest valid fact,
(c) non-destructive supersession (keep the old fact, mark it superseded).

### What this supports for the gnosis roadmap

1. **Append-only + read-time recency: keep it, add deterministic supersession at read time.**
   The strongest measured result in the space (2606.01435) is exactly this design: append
   everything with timestamps, detect same-slot candidates at retrieval, pick newest
   deterministically in code — not via the answer LLM and not via write-time DELETE. Zep-style
   bi-temporal *invalidation as an LLM write-time process* is not supported by evidence
   (7% FactConsolidation). **Bi-temporal timestamps (event-time + ingest-time) on every fact:
   yes, now — cheap and a prerequisite for everything else. Bi-temporal invalidation logic at
   write time: later or never.**
2. **Scheduled reflection/consolidation: modest, conditional yes — for dedup, not fact
   editing.** Mastra's Reflector shows consolidation can coexist with top knowledge-update
   scores, but LongMemEval failure analyses show consolidation is also the main source of
   overwrite errors. If added: merge near-duplicates and mark supersession links, never delete
   originals.
3. **Add a store-time quality gate eventually.** 2505.16067 shows indiscriminate accumulation
   degrades results measurably; a cheap "worth storing / is this a duplicate" check is
   evidence-backed.

### Membench aging protocol (concrete)

- **Phase A (ingest):** ingest LOCOMO/LongMemEval corpus normally; record baseline QA accuracy.
- **Phase B (age):** inject, per conversation, N synthetic sessions containing (i) exact and
  paraphrase near-duplicates of stored facts (~30%), (ii) explicit updates superseding k known
  answer-bearing facts ("I moved from X to Y"), (iii) contradictions without clear recency
  cues, (iv) irrelevant filler. Timestamp sessions weeks/months apart (synthetic clock).
- **Phase C (re-ask):** re-run the same QA set plus update-targeted questions.
- **Metrics:** (1) **retention** — accuracy on unchanged facts, Phase C vs A (degradation from
  noise/duplicates); (2) **supersession accuracy** — % of updated-fact questions answered with
  the *new* value; (3) **stale-answer rate** — % answered with the old value (worse than
  wrong); (4) **store growth ratio** — memories stored / unique facts; (5) optionally accuracy
  vs N (aging curve, à la 2606.27472's 24× length sweep). LongMemEval's knowledge-update
  subset is the external calibration point for metric 2.

---

## Sources

Gap 1: [arXiv:2411.06037](https://arxiv.org/pdf/2411.06037) ·
[Google Research blog](https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/) ·
[arXiv:2506.09038](https://arxiv.org/html/2506.09038v1) ·
[arXiv:2410.10813](https://arxiv.org/html/2410.10813v2) ·
[arXiv:2602.15313](https://arxiv.org/pdf/2602.15313) ·
[arXiv:2604.11563](https://arxiv.org/pdf/2604.11563) ·
[arXiv:2606.24725](https://arxiv.org/pdf/2606.24725) ·
[arXiv:2512.11614](https://arxiv.org/html/2512.11614) ·
[arXiv:2409.16146](https://arxiv.org/html/2409.16146v1) ·
[arXiv:2605.18792](https://arxiv.org/pdf/2605.18792) ·
[arXiv:2506.00054](https://arxiv.org/html/2506.00054v1) ·
[mem0 benchmarks 2026](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)

Gap 2: [arXiv:2606.01435](https://arxiv.org/html/2606.01435v1) ·
[arXiv:2505.16067](https://arxiv.org/html/2505.16067v2) ·
[arXiv:2606.27472](https://arxiv.org/html/2606.27472) ·
[arXiv:2604.15774](https://arxiv.org/abs/2604.15774) ·
[arXiv:2501.13956](https://arxiv.org/pdf/2501.13956) ·
[Mastra OM](https://mastra.ai/research/observational-memory) ·
[Chronos, arXiv:2603.16862](https://arxiv.org/pdf/2603.16862) ·
[Memanto, arXiv:2604.22085](https://arxiv.org/pdf/2604.22085) ·
[mem0 research](https://mem0.ai/research-3) ·
[ByteRover blog](https://www.byterover.dev/blog/benchmark-ai-agent-memory) ·
[Memoria on LongMemEval](https://medium.com/@matrixorigin-database/benchmarking-memoria-on-longmemeval-strong-memory-retrieval-clear-reader-separation-ee6c89c75d76) ·
[Vending-Bench, arXiv:2502.15840](https://arxiv.org/pdf/2502.15840) ·
[arXiv:2605.17830](https://arxiv.org/html/2605.17830v1)

Both categories: [Memoria/MatrixOrigin LongMemEval run](https://medium.com/@matrixorigin-database/benchmarking-memoria-on-longmemeval-strong-memory-retrieval-clear-reader-separation-ee6c89c75d76)
(reader-model separation on identical retrieval).
