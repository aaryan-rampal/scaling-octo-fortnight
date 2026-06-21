# Rung ③ minting strategy — research

Scope: **how the single consolidation pass proposes principles**, and nothing
else. Rung ③ reads the memory pile (Hindsight `recall` over the bank) and writes
one-line `Principle`s, each backed by an evidence ledger of ≥2 supporting
`memory_id`s plus a confidence score. The swarm (retriever/critic/arbiter) and
the contradiction flywheel are **out of scope** (CLAUDE.md §3) — not proposed
here. This doc decides only the internal strategy left open by
`docs/v0-pipeline-contract.md` and `docs/raw-to-principles-research.md` §3.

Authority: `raw-to-principles-research.md` §3 (the rung-③ template is Generative
Agents' reflection tree, confidence is derived from the ledger, not the LLM).
Citations below are looked-up, not from memory.

---

## 1. The open question

A principle must be (a) **grounded** — entailed by real memories, not invented;
(b) **provenance-faithful** — the stored `memory_id`s are the ones that actually
back it, not post-hoc decoration; (c) **cheap and repeatable** enough for a 24h
v0 over ~389 source events (a small bank). Three ways to structure the pass:

- **(A) Cluster-first** — group related recalled memories, then ask the LLM to
  propose principles per cluster; each principle cites ≥2 `memory_id`s drawn
  from that cluster's input set.
- **(B) Single global call** — feed all recalled memories (indexed) to one LLM
  call, ask for top-N principles + cited evidence indices.
- **(C) Reflection-tree (question→insight)** — Generative Agents' two-step: ask
  the LLM for salient high-level *questions* over the memories, retrieve per
  question, then extract insights with cited evidence indices.

---

## 2. Why provenance fidelity is the deciding axis

The principle's whole value is that it traces to ground truth (CLAUDE.md §2).
That makes **citation faithfulness**, not fluency, the property to optimize.

The literature is blunt that LLM-emitted citations are often *unfaithful*:
correctness ≠ faithfulness, and up to **57% of citations in RAG outputs are
"post-rationalized"** — the model answers from parametric memory, then
token-matches a source to point at, so the citation looks grounded without being
causally grounded ([Wallat et al., 2024, arXiv:2412.18004](https://arxiv.org/pdf/2412.18004)).
Generation-time and post-hoc citation both leave ~37–41% human-judged
hallucination rates ([Saxena et al., 2025](https://arxiv.org/html/2406.15264)).
The defensive pattern that survives is **structural**: pin the candidate
`memory_id`s to the exact input set the LLM was shown, then verify each cited id
with a non-LLM check (the id must exist in that set). Path-based refs are more
trustworthy than free-form LLM citations.

This is the axis on which A, B, C separate:

- **B (global)** gives the model the entire pile and asks it to both *select*
  and *cite*. The cited indices are the weakest link — most room to
  post-rationalize, and an `id` it invents or mis-maps is hard to bound because
  any of N memories was "in scope."
- **A (cluster-first)** narrows the candidate set per call. The LLM only ever
  sees one cluster, so every legal citation is a member of a small, known set; a
  post-hoc script can reject any `memory_id` not in that cluster. Smaller,
  topically coherent inputs also reduce hallucination on their own — grounded
  summarization over tight clusters lands far lower error than over large mixed
  inputs ([clustering-before-summarization survey, ACL 2025](https://aclanthology.org/2025.acl-long.902/);
  CRAG cut prompt tokens 46–90% with no quality loss).
- **C (reflection-tree)** is the Generative Agents original: the
  question-then-retrieve step *is* a soft clustering (each question pulls a
  focused memory set), and the insight prompt cites record indices —
  `"dedicated to research (because of 1, 2, 8, 15)"`
  ([Park et al., UIST'23, arXiv:2304.03442](https://ar5iv.labs.arxiv.org/html/2304.03442)).
  Strong grounding, but it adds an extra LLM round (question generation) and the
  question step is a non-deterministic fan-out that's harder to test with
  fixtures.

---

## 3. Comparison

| Axis | A — Cluster-first | B — Single global | C — Reflection-tree |
|---|---|---|---|
| Can a principle be falsely "supported"? | low — LLM only sees one cluster; cited ids verifiable against a small set | **highest** — whole pile in scope, most post-rationalization room | low — focused per-question sets, but two LLM stages to audit |
| Provenance fidelity | high — candidate ids fixed to cluster input; script-verifiable | weak — selection + citation in one shot over all N | high — cited indices per question; original GA design |
| Cost / LLM calls | 1 embed pass (or none) + 1 call/cluster (k≈3–8 on this bank) | 1 call | 2+ calls (questions, then insight/cluster) + retrieval |
| Determinism | medium — clustering is deterministic given embeddings; only the per-cluster prompt is stochastic | low — one big stochastic call | lowest — stochastic question fan-out drives everything |
| Fit for 24h v0 / small bank | **best** — simple, bounded, testable; clusters give natural ≥2-memory groups | simplest to write but worst grounding | most faithful long-term, most moving parts to build/test now |

Notes for this bank specifically: ~389 source events → a **small** memory pile
after segmentation+retain (the 7-day slice is spotify-heavy, 218/389, so many
memories are low-information play facts). On a pile this small, B's "context
window" argument for a single call is real (it all fits), but small size does
*not* fix post-rationalization — the faithfulness gap is independent of whether
the input fits. Clustering still pays off because it (i) bounds the citation set
per call and (ii) gives the ≥2-memories test a natural unit: a cluster of size 1
is rejected before any LLM call, for free.

On *when* to run: both Generative Agents (importance-sum gated) and Letta's
sleep-time compute (background idle passes) run consolidation off the
interaction path
([Letta sleep-time compute, 2025](https://www.letta.com/blog/sleep-time-compute)).
For v0 this is just a manual batch pass after retain — scheduling is not part of
the open question, but the gate (run only when enough new memories accumulate)
carries over cheaply.

---

## 4. Confidence from the ledger, not the LLM

LLM verbalized confidence is systematically overconfident and **RLHF makes it
worse** — reward models favor confident-sounding text regardless of correctness;
RLHF-tuned models cluster stated confidence in 80–100% with ECE up to 0.30
([Leng et al., ICLR 2025, arXiv:2410.09724](https://arxiv.org/abs/2410.09724);
[Mind the Confidence Gap, 2025](https://arxiv.org/html/2502.11028)). So do not
ask the model "how sure are you?". Derive confidence from the **structure of the
evidence ledger** — the signals the KB/fact-verification literature converges on
are count, source diversity, recency, and signed contradictions
([Bayesian evidence→belief, 2504.19622](https://arxiv.org/pdf/2504.19622);
multi-signal fact-verification confidence,
[2510.22751](https://arxiv.org/pdf/2510.22751)).

The ledger row (from `raw-to-principles-research.md` §3) is
`(memory_id, stance ∈ {supports, weakens, contradicts}, quote, ts)`. Recommended
v0 formula — a bounded, monotone function of the ledger, no learned params:

```
let S = # supports, W = # weakens, C = # contradicts   (distinct memory_ids)
let D = # distinct sources among supporting memories     (source diversity)
let R = max recency weight over supports, r_i = 0.5 ** (age_days_i / H), H = 30d

raw       = S + 0.5*D + R  - W - 2*C          # supports & diversity up; contradictions down hard
confidence = clip(raw / (S + W + 2*C + 3), 0, 1)   # normalize; +3 keeps thin evidence humble
```

Properties: thin evidence (S=2, no diversity, no contradictions) lands modest
(~0.4–0.5), not confident; a contradiction counts double against (matches the
endorsement/contradiction-sum pattern in KB veracity work); source diversity and
recency lift it; everything is recomputable from the ledger and decays as
supports age (recency half-life H=30d — tunable, and time-decay of
un-reinforced beliefs is itself novel per §3). This is a starting rule to
instrument, not a tuned one; the constants (0.5, 2, +3, H) are the knobs.

### The ≥2-memories + novelty checks (gate before writing)

Two cheap, structural guards run *before* a principle is accepted — both
checkable without trusting LLM self-report:

1. **≥2 distinct supporting `memory_id`s.** Reject any candidate whose ledger has
   fewer than two distinct supports. With cluster-first this is automatic:
   singleton clusters never reach the LLM. (Genuine synthesis, not a restatement
   of one memory — `raw-to-principles-research.md` §3.)
2. **Novelty / "not equal to any single memory."** The principle must not be a
   paraphrase of one supporting memory. Cheap check: embed the principle and each
   cited memory; reject if max cosine similarity to any single memory exceeds a
   threshold (≈0.9). This catches the "fluent restatement" failure that the
   ≥2-count alone misses (two near-identical memories could otherwise pass). An
   LLM-judge novelty check is the heavier alternative; the embedding check is the
   v0 default — deterministic and free of the miscalibration problem.

---

## 5. v0 recommendation — **A (cluster-first)**

Build the minting pass as **cluster-first**: embed the recalled memories,
cluster them (deterministic — e.g. agglomerative/HDBSCAN over embeddings, or a
similarity-threshold grouping; no LLM), drop singleton clusters, then make one
LLM call per cluster asking for at most one or two principles, each citing ≥2
`memory_id`s **from that cluster only**, and verify every cited id against the
cluster's input set with a plain script before writing. Apply the novelty check,
then compute confidence from the ledger with the §4 formula.

Rationale: provenance fidelity is the property that makes a principle worth
anything, and it's exactly where the single global call (B) is weakest — the
post-rationalization rate is high and unbounded when the model can cite anything
in a large pile. Cluster-first bounds the citation set per call so a non-LLM
script can guarantee every stored `memory_id` was genuinely in scope, gives the
≥2-memories rule a free structural unit (cluster size), and keeps cost to a
handful of small calls on this small bank. It captures most of the
reflection-tree's (C) grounding benefit — the question step is itself a soft
clustering — without C's extra stochastic LLM stage and harder-to-fixture
fan-out, which matters for a 24h v0. Reflection-tree (C) is the right *upgrade*
once the pass is stable and we want higher-order, recursive insights.

**One-line confidence rule:** `confidence = clip((S + 0.5*D + R - W - 2*C) /
(S + W + 2*C + 3), 0, 1)` over the ledger (S/W/C = distinct supporting/weakening/
contradicting memory_ids, D = distinct sources, R = recency half-life weight,
H=30d) — never the LLM's self-reported confidence.

**Risks flagged:**
- Even cluster-first LLM citations can post-rationalize *within* a cluster — the
  non-LLM id-membership check bounds *which* ids, not *whether* each truly
  entails the principle. The embedding novelty check is the only v0 guard
  against fluent restatement; an NLI/entailment verifier is the honest fix and
  is post-v0.
- Spotify dominates this 7-day slice (218/389), so clusters may skew toward
  low-information play facts and mint shallow "listens to X" principles. Consider
  down-weighting or a per-source importance gate so music volume doesn't crowd
  out sparser-but-richer imessage/photo memories.
- The confidence constants (0.5, 2, +3, H=30d) are untuned guesses with no
  labeled ground truth on this bank — treat the formula as instrumentation to
  watch, not a calibrated score, and don't surface raw numbers to the user as if
  they were.
```