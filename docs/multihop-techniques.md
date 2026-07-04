# Multi-hop & open-domain techniques for gnosis: a skeptical, targeted survey

*Compiled 2026-07-04. Targeted follow-up to `frontier-2026.md`, scoped to our two stuck categories —
**multi-hop (~34–42)** and **open-domain (~33–43, n=21, noisy)** — and to the cross-category
**interference** problem (hybrid: temporal+/multi-hop−; abstention: adversarial+/answerable−). Every
load-bearing number was verified against the primary paper/repo where fetchable; anything we could not
verify is flagged inline. Evidence graded **peer-reviewed / preprint / vendor**. Techniques already tried
or already covered in `frontier-2026.md` (hybrid BM25+RRF, local reranker, sufficiency-rewrite loop,
graph-route union, multi-granularity, RL extractor, temporal validity intervals) and the systems we
already know (HippoRAG-2 PPR, Zep bi-temporal, Generative-Agents reflection, MemGPT, EMem EDUs,
Mnemis dual-route, EverMemOS MemCells) are **not** re-recommended.*

---

## 0. Read this first — three skeptical priors that gate everything below

**(a) The strong multi-hop ablations are all on Wikipedia, not conversation.** IRCoT, self-ask, DecomP,
Adaptive-RAG, EfficientRAG — every technique with a *clean* multi-hop ablation was measured on HotpotQA /
2WikiMultihopQA / MuSiQue / IIRC (structured Wikipedia bridge questions). We searched specifically for a
published application of self-ask / IRCoT / query-decomposition to **LOCOMO or LongMemEval multi-hop** and
**found none** (the closest, `arXiv:2606.21553`, is HotpotQA-only on a 7B model). So every "multi-hop
lever" below is a **transfer hypothesis** — the mechanism is peer-reviewed, its efficacy *on conversational
memory* is not. This is exactly why they are gnosis-side experiments to be A/B'd, not settled facts.

**(b) Open-domain is the universally-weakest category — even for systems that already do the thing we'd
add.** In every frontier table we verified, open-domain is the *lowest* per-category score: Mnemis 82.3,
EverMemOS **76.04**, MemU 77.1 — each system's own floor. EverMemOS *already* builds hierarchical
"MemScene" cluster-summaries and still bottoms out on open-domain. HORMA (`arXiv:2606.11680`), which adds a
RAPTOR-like hierarchical summary tree and tests it **on LOCOMO/LongMemEval**, reports its win as
**efficiency (≤22.17% of baseline tokens), not accuracy**. Net: no technique has a *verified accuracy*
ablation that cracks open-domain on conversational memory. Combined with our n=21 (treat <8–10 pt swings as
noise), open-domain is the lowest-confidence target on this page — build for it last, and instrument before
believing any delta.

**(c) Generic graph-RAG can HURT conversational memory.** A 2026 comparison notes LightRAG, MiniRAG and
KG-Retriever "underperform on both [LOCOMO/LongMemEval] due to their reliance on entity-/relation-level
graphs that lack alignment with conversational granularity" (surfaced via SGMem/LiCoMemory discussion;
`arXiv:2509.21212`, `arXiv:2511.01448` — preprint). This is a direct caution for **both** the entity-graph
we're building **and** any community-summary layer: the graph has to be aligned to conversational turns,
not imported wholesale from document-RAG. And per the ConvoMem critique (`arXiv:2511.10523`, preprint),
plain filesystem retrieval already hits ~74% on LOCOMO — some of our "multi-hop gap" may be shallow-retrieval
measurement artifact, not reasoning. Report per-category deltas under our own GPT-5.5 judge only; nothing
here is comparable to published absolute scores (see `frontier-2026.md` §0).

---

## 1. Ranked techniques (max 5)

Scoring lens: expected delta on **our** weak categories × evidence quality **on multi-hop specifically** ÷
implementation cost, with an explicit penalty for anything that risks our protected abstention/adversarial
strength (aggressive retrieval manufactures false support — Mnemis's excluded adversarial sits at 34.3%,
the cautionary tale).

---

### T1 — Query decomposition + interleaved/iterative retrieval (self-ask / IRCoT) driven over the entity graph
**The multi-hop lever. Highest ceiling; the thing that makes the in-progress entity graph actually pay off.**

- **Mechanism.** Break a compositional question ("where did X's employer's founder study") into **dependent**
  sub-questions, where hop-2's query is only formable *after* hop-1 resolves the bridge entity. Two verified
  variants: **self-ask** (`arXiv:2210.03350`, EMNLP-Findings 2023 — the model emits explicit follow-up
  questions, each answerable by a retrieval call, then composes) and **IRCoT** (`arXiv:2212.10509`, ACL 2023 —
  interleave one CoT sentence → retrieve on it → extend CoT → retrieve again). In gnosis, hop-2 is a
  **traversal of the entity graph we're materializing**: sub-q1 retrieves and pins the bridge entity node,
  sub-q2 is a bounded Cypher expansion from that node. This is *why* graph-QA fusion was a no-op standalone —
  a graph with nothing driving the second hop is inert; decomposition is the driver.
- **Distinct from what we've tried / covered.** Not the discriminative "LLM recall filter" (that *discarded*
  candidates, flat). Not `frontier-2026.md` T4 "sufficiency + multi-query rewrite" (that emits 2–3 **parallel
  reformulations of the same question** for recall). This is **sequential, dependency-structured**
  decomposition where hop-2 literally cannot be written until hop-1 answers — the mechanism that finds the
  bridge entity our 1024-dim dense (and even hybrid BM25) never surfaces because it isn't in the query text.
- **Evidence — peer-reviewed, but Wikipedia-only (the caveat that matters).** IRCoT: up to **+21 retrieval /
  +15 QA** across HotpotQA/2Wiki/MuSiQue/IIRC vs one-shot retrieval, transfers to smaller models (Flan-T5)
  without training. `arXiv:2606.21553` (preprint, Qwen-7B, HotpotQA) ran the component ablation and concludes
  **query decomposition is the single most impactful component**, with iterative-retrieval *depth* second —
  "the depth of the loop is more consequential than individual retrieval strategies." **No conversational-memory
  ablation exists** (verified). Grade: strong on multi-hop *as a task*, unproven on *our* data.
- **Expected gain (ours).** Multi-hop is where our headroom is largest and this is its canonical fix. But it's
  a transfer bet; and each extra retrieval round can manufacture false support → **abstention/adversarial
  regression risk** on our protected category. Ship it *with* T2 as the guardrail.
- **Cost — medium.** Answer-side/gateway loop: +1–3 LLM calls on multi-hop queries, a hard round cap (2), a
  cheap "is this multi-hop?" gate so single-hop/temporal aren't taxed (→ T3), and Cypher traversal plumbing
  that mostly exists once the entity graph lands.
- **How membench measures it.** Multi-hop-category delta on subset-3; **hard gate on adversarial/answerable
  non-regression** (this is the acceptance criterion, not a nice-to-have); retrieval-recall@k against gold
  multi-hop evidence turns (add this instrument regardless); LLM-calls/query and p95 latency; fire-rate of the
  multi-hop gate.

---

### T2 — Chain-of-Note / structured read-then-reason over retrieved facts
**Cheapest, the *only* answer-side technique with conversational-memory evidence, and abstention-safe. Ship first or alongside T1.**

- **Mechanism.** Before answering, the reader writes a per-item **note** (is this fact relevant? what does it
  say? does it contradict others?) over each retrieved fact/turn, *then* synthesizes — filtering distractors
  in-context instead of trusting top-k. JSON-structured notes outperform prose.
- **Why it targets our exact failure.** We observed "hybrid BM25 HURTS multi-hop — surfaces similar-but-wrong
  facts." Chain-of-Note is the direct antidote: it lets the reader **reject the similar-but-wrong fact in the
  note step** rather than answering from it. It also *raises* rejection/abstention (protecting adversarial),
  making it the rare multi-hop play that doesn't threaten our strength.
- **Evidence — peer-reviewed AND conversational-memory-specific (the strongest on this page for our setting).**
  Chain-of-Note (`arXiv:2311.09210`, EMNLP 2024): **+7.9 EM under fully-noisy retrieval, +10.5 rejection rate**
  on out-of-scope questions. Crucially, **LongMemEval** (`arXiv:2410.10813`) applies it to *conversational
  memory*: CoN + structured (JSON) reading gives **up to +10 absolute QA points across three readers**, and —
  the killer datum — **"even with perfect retrieval, a suboptimal reading strategy costs up to 10 points."**
  Reading, not just retrieval, is a first-class lever, and it's the one with a memory-native number.
- **Expected gain (ours).** Multi-hop (distractor rejection) + open-domain (synthesis over many notes) +
  abstention-safe. Smaller per-category ceiling than T1 but far cheaper and lower-risk; likely the better
  *first* move.
- **Cost — LOW.** A reader-prompt change only. No schema, no index, no extra retrieval. Retrieval-agnostic —
  composes with everything else we build.
- **How membench measures it.** Reader-prompt A/B at *identical* retrieval, per-category (multi-hop, open-domain,
  adversarial, answerable). Watch answerable-category for over-abstention (the note step can make the reader
  too cautious — same failure mode as our abstention prompt). Report token cost of the note pass.

---

### T3 — Adaptive / routed retrieval: classify query type, apply the per-category-best strategy
**The direct fix for the interference problem they asked about — keep each category's peak instead of trading them off.**

- **Mechanism.** A cheap classifier tags each query (single-hop / multi-hop / temporal / abstention-prone /
  aggregative-open-domain) and **routes to the strategy that won that category in ablation**, instead of one
  global pipeline. Concretely for us: temporal → hybrid-BM25+date-match (our measured temporal win);
  multi-hop → T1 decomposition + graph traversal; abstention-prone → strict evidence-grounded prompt; simple
  single-hop → cheap dense, no loop. This is the literature answer to "hybrid helps temporal but hurts
  multi-hop; abstention prompt helps adversarial but hurts answerable" — stop applying one setting globally.
- **Evidence — peer-reviewed core (Wikipedia) + convergent 2026 memory preprints (soft).** Adaptive-RAG
  (`arXiv:2403.14403`, NAACL 2024): a small query-complexity classifier routes to no-/single-/multi-step
  retrieval and **beats every static baseline on the accuracy-efficiency frontier** across open-domain QA.
  Memory-specific convergence, all **preprint / unverified numbers**: AgentIR (`arXiv:2605.25092`, USC,
  workload-adaptive cascade that conditionally fuses BM25/SPLADE/HNSW by query type; reports a soft router
  beating static systems on LongMemEval — **but its headline "0.274" could not be confirmed as accuracy vs a
  retrieval metric; the low absolute value is a red flag; no repo confirmed**); MemRouter (`arXiv:2605.00356`),
  MemFlow (`arXiv:2605.03312`), MemORAI (`arXiv:2605.01386`) all propose per-intent routing for conversational
  memory. Grade: the *principle* has peer-reviewed backing and heavy 2026 convergence; the *memory numbers*
  are unverified preprints — treat as a design pattern, not a settled gain.
- **Expected gain (ours).** This is a **meta-fix**: the gain is recovering the *losing side* of each tradeoff
  we've already measured (the multi-hop we lose to hybrid; the answerable we lose to the abstention prompt).
  It has no ceiling of its own — it's only as good as the per-category strategies it routes to, which is why
  it comes *after* T1/T2/hybrid exist.
- **Cost — medium.** One classifier (start few-shot LLM or a small trained head over LOCOMO categories) + a
  routing table. Main risk is **misroute** (classifier error sends a multi-hop question down the single-hop
  path) — bounded by keeping a safe default and measuring the confusion matrix.
- **How membench measures it.** Per-category deltas of router-vs-each-static-strategy; acceptance criterion =
  **no category regresses below its own static best**; classifier confusion matrix + per-route fire-rates;
  latency (routing should *save* compute on simple queries).

---

### T4 — Hierarchical / community summary nodes for open-domain aggregation (RAPTOR + GraphRAG-community)
**The open-domain lever — but the weakest-evidenced entry here; build last, instrument hard.**

- **Mechanism.** Build summary nodes *above* raw turns so aggregative "what did they discuss about X across
  sessions" queries read a summary, not scattered turns. Two verified constructions: **RAPTOR**
  (`arXiv:2401.18059`, ICLR 2024 — recursively cluster + abstractively summarize, retrieve at mixed tree
  levels) and **GraphRAG community summaries** (`arXiv:2404.16130`, Microsoft — Leiden communities over the
  entity graph, pre-generated summaries, map-reduce over them for global questions). **Graphiti (Zep) already
  implements this on a Neo4j substrate via label-propagation communities** — directly portable to our stack.
- **Evidence — peer-reviewed but off-domain; vendor/qualitative on-domain (the gap that matters).** RAPTOR:
  **+20% on QuALITY**, NarrativeQA ROUGE-L 30.87 vs 29.26 — but on *documents/narratives*, not conversation.
  GraphRAG: large **comprehensiveness/diversity** wins on global sensemaking — but those are **LLM-graded
  qualitative rubrics over document corpora, not LOCOMO accuracy**. Graphiti's community summaries ship inside
  Zep, whose LOCOMO number **collapsed 84 → 58.44 under corrected protocol** (`getzep/zep-papers` #5). HORMA
  (`arXiv:2606.11680`, preprint) puts a hierarchical tree *on LOCOMO/LongMemEval* and wins on **efficiency,
  not accuracy**. And EverMemOS's MemScene cluster-summaries still leave open-domain its *worst* category.
  Grade: **no verified accuracy ablation cracks open-domain on conversational memory.**
- **Expected gain (ours).** Open-domain, our 2nd-weakest — but see §0(b): universally hard, n=21 noisy,
  even systems that already do this bottom out here. Expect a *modest, hard-to-measure* delta. Upside: the
  summary layer sits naturally on the entity graph we're already building (community detection is cheap once
  nodes+edges exist).
- **Cost — medium-high.** Build-time clustering + summary generation + maintenance. Graphiti's
  label-propagation avoids full rebuilds (incremental, our substrate); RAPTOR needs periodic re-cluster. Heed
  §0(c): align communities to conversational granularity or it can *hurt*.
- **How membench measures it.** Open-domain-category delta (report n=21; <8–10 pt = noise). Binary J is a poor
  fit for aggregative answers — add a **coverage/comprehensiveness rubric** (did the answer name the K topics
  the gold summary names?) before crediting anything.

---

### T5 — (Watch, not build) Self-RAG / reflection-token adaptive retrieval
**A trained alternative to T3's routing; parked for the same reason as Memory-R2 in `frontier-2026.md`.**

- **Mechanism.** Self-RAG (`arXiv:2310.11511`, ICLR 2024) trains the model to emit **reflection tokens** that
  decide *when* to retrieve and *critique* whether retrieved evidence supports each sentence — adaptive
  retrieval + self-verification learned end-to-end, rather than a separate classifier (T3) or prompt (T2).
- **Evidence — peer-reviewed, off-domain.** Beats standard RAG and ChatGPT on open-domain QA / fact
  verification / long-form. **No conversational-memory evaluation; requires fine-tuning a reader** we don't
  control at inference.
- **Why watch, not build.** Training-required (like Memory-R2's `frontier-2026.md` T6); T2 (prompt-level
  note-taking) and T3 (external routing) get ~80% of the behavior with zero training. Revisit only if
  T2/T3 plateau *and* we invest in a local tuned reader.
- **How membench would measure it.** Only relevant if a local reader is trained — then per-category deltas +
  OOD transfer to LongMemEval_S, mirroring Memory-R2's protocol.

---

## 2. Summary table

| # | Technique | Targets | Evidence grade | Multi-hop ablation on *conversation*? | Cost | Abstention risk |
|---|---|---|---|---|---|---|
| **T1** | Query decomposition + iterative/interleaved retrieval over the entity graph (self-ask/IRCoT) | **multi-hop** | peer-reviewed (Wikipedia only) | **No** — transfer bet | medium | **yes** — gate it |
| **T2** | Chain-of-Note structured read-then-reason | multi-hop, open-domain, abstention-safe | **peer-reviewed + LongMemEval (memory-native)** | partial (LongMemEval overall +10pp) | **low** | none / positive |
| **T3** | Adaptive/routed retrieval by query type | **interference fix** (all categories) | peer-reviewed core + preprint memory convergence | classifier only; routed strategies carry the gain | medium | low (protects each peak) |
| **T4** | Hierarchical/community summary nodes (RAPTOR / GraphRAG-community / Graphiti) | open-domain | peer-reviewed off-domain; vendor/qualitative on-domain | **No verified accuracy win on conversation** | med-high | low |
| **T5** | Self-RAG reflection-token adaptive retrieval (**watch**) | multi-hop, adaptive | peer-reviewed, off-domain, training-required | No | high (training) | low |

---

## 3. The single highest-ROI next technique after the entity graph

**T1 — query decomposition / self-ask iterative retrieval that traverses the entity graph — shipped with T2
(Chain-of-Note) as its mandatory guardrail.**

Rationale in one breath: our multi-hop is stuck precisely because the bridge entity is never in the query
text, so neither dense nor hybrid BM25 retrieves it, and a materialized entity graph with nothing driving
the second hop is inert (that's why graph-QA fusion was a no-op). **Sequential, dependency-structured
decomposition is the one mechanism that (a) has a peer-reviewed *multi-hop* ablation naming it the single
most impactful component, and (b) directly converts the entity-graph investment we're already making into
multi-hop answers** by turning hop-2 into a Cypher traversal from the pinned bridge node. It's a transfer
bet (no conversational-memory ablation exists — §0a) and it risks our abstention strength, which is exactly
why it ships in the same PR as **T2's Chain-of-Note reading** — the low-cost, LongMemEval-proven,
abstention-*positive* layer that rejects the "similar-but-wrong facts" a wider retrieval will surface. T2
alone is the safer standalone win; T1+T2 together is the highest-ceiling next move, and **T3 (routing) is
the immediate follow-up** so the multi-hop loop only fires on multi-hop queries and never taxes the temporal
and answerable categories we've already made strong.

---

## 4. Verification ledger — what we could NOT verify

- **The core caveat:** no published work applies self-ask / IRCoT / query-decomposition to LOCOMO or
  LongMemEval multi-hop (searched explicitly; none found). All T1 evidence is Wikipedia multi-hop.
- **AgentIR (`arXiv:2605.25092`):** PDF metadata would not yield per-category numbers; the "0.274 on
  LongMemEval" figure could not be confirmed as accuracy vs a retrieval metric (low value suggests the
  latter); no repo confirmed. Treated as pattern-corroboration only.
- **HORMA (`arXiv:2606.11680`):** LOCOMO/LongMemEval results confirmed as *efficiency* (≤22.17% tokens);
  no accuracy-delta table extracted.
- **MemRouter / MemFlow / MemORAI (`arXiv:2605.00356` / `2605.03312` / `2605.01386`):** existence and
  routing thesis confirmed via search; per-category numbers not fetched — preprint, cited as convergence
  only, not as evidence for a gain.
- **`arXiv:2606.21553` (agentic-RAG component ablation):** decomposition-is-most-impactful conclusion
  confirmed; exact per-component point values not cleanly extracted from the PDF; HotpotQA/7B only.
- **GraphRAG / RAPTOR:** peer-reviewed and verified, but no fetched source shows an *accuracy* result on
  conversational-memory open-domain; the on-domain claim (Graphiti communities) rides on Zep's
  audit-collapsed numbers.
- **LOCOMO itself:** per `frontier-2026.md` §0 — 6.4% wrong gold answers, ~62.8% acceptance of
  wrong-but-topical answers, and the ConvoMem critique (filesystem ≈74%) — our multi-hop "gap" is partly a
  measurement artifact. Per-category deltas under our own GPT-5.5 judge are the only real signal.

## Sources

Multi-hop / reasoning: [IRCoT arXiv:2212.10509](https://arxiv.org/abs/2212.10509) ·
[Self-Ask arXiv:2210.03350](https://arxiv.org/abs/2210.03350) ·
[Chain-of-Note arXiv:2311.09210](https://arxiv.org/abs/2311.09210) ·
[Agentic-RAG ablation arXiv:2606.21553](https://arxiv.org/pdf/2606.21553) ·
[Self-RAG arXiv:2310.11511](https://arxiv.org/abs/2310.11511)

Open-domain / hierarchical: [RAPTOR arXiv:2401.18059](https://arxiv.org/abs/2401.18059) ·
[GraphRAG arXiv:2404.16130](https://arxiv.org/abs/2404.16130) ·
[HORMA arXiv:2606.11680](https://arxiv.org/abs/2606.11680) ·
[Graphiti/Zep arXiv:2501.13956](https://arxiv.org/html/2501.13956v1)

Adaptive / routed: [Adaptive-RAG arXiv:2403.14403](https://aclanthology.org/2024.naacl-long.389/) ·
[AgentIR arXiv:2605.25092](https://arxiv.org/pdf/2605.25092) ·
[MemRouter arXiv:2605.00356](https://arxiv.org/html/2605.00356) ·
[MemFlow arXiv:2605.03312](https://arxiv.org/html/2605.03312) ·
[MemORAI arXiv:2605.01386](https://arxiv.org/html/2605.01386v1)

Memory-native anchor / critiques: [LongMemEval arXiv:2410.10813](https://arxiv.org/html/2410.10813v2) ·
[ConvoMem arXiv:2511.10523](https://arxiv.org/pdf/2511.10523) ·
[SGMem arXiv:2509.21212](https://arxiv.org/html/2509.21212v1) ·
[LiCoMemory arXiv:2511.01448](https://arxiv.org/html/2511.01448v2)
