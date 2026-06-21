# PROMPT.md — point your Claude here to learn the raw→principles work

**Teammate: paste this whole file (or "read PROMPT.md and follow it") to your
Claude Code session in this repo.** It onboards you to the raw-data → principles
vertical that was built on the `aaryan-principles` branch.

---

## Claude: your job

You are onboarding a teammate to the **raw→principles pipeline**. Before
explaining anything, **ask them these two questions and wait for answers:**

1. **Depth** — how deep do they want to go?
   - **(a) Orientation** — the 5-minute "what is this and does it work" tour.
   - **(b) Working knowledge** — enough to run the pipeline and modify a rung.
   - **(c) Deep dive** — the design decisions, pivots, and invariants, enough to
     extend it or defend it.
2. **Their context** — what's their role / what are they here to do? (e.g.
   building the web UI, adding a data source, tuning principle quality, doing the
   demo, reviewing the architecture.) Tailor everything to that.

Then guide them through the material below at the depth they chose, **in order**,
checking understanding as you go. Don't dump it all at once — teach it. Read the
files yourself first so you can answer follow-ups from the actual code, not memory.
When a fact here conflicts with what's on disk, trust the disk and say so.

---

## The one-paragraph version (everyone gets this)

We ingest a person's own data (iMessage, photos, Spotify, Claude chat exports),
fold it into a memory network via Hindsight, and mint **principles** — short,
one-line mental models ("You value preserving human experience to combat a fear
of impermanence") that are **traceable** all the way back to the raw messages
that produced them. The headline output is `data/principles.json`: 12 grounded,
non-obvious principles, each citing ≥2 source memories. It works end to end today.

---

## Reading order (point them here by depth)

**Always start with:**
- `CLAUDE.md` — the authoritative seed: what's real vs. vision, the stack, the
  rules. **§2 (provenance is the path) and §3 (POC vs. vision) are non-negotiable.**
- `docs/PIPELINE_FLOW.md` — the current end-to-end flow, the 5 steps + commands,
  what each rung does. **This is the map.**

**Working knowledge (b) adds:**
- `scripts/mint_principles.py` + `src/pipeline/propose.py` — how principles are
  actually minted (recall → cluster → gemini propose → guard → write). The
  observability + `--dry-run`/`--limit` pattern is here; copy it for any new step.
- `src/pipeline/mint.py` — the deterministic engine: clustering, citation
  verification, novelty, ledger-confidence. Pure + unit-tested.
- `data/principles.json` (+ `data/principles.v1.json`) — the actual output. Diff
  them to see the prompt-quality improvement (see Pivots below).

**Deep dive (c) adds:**
- `docs/v0-pipeline-contract.md` — the pinned shapes for every rung (Event →
  Episode → Unit → Memory → Principle → Edge).
- `docs/rung3-minting-strategy.md` — why cluster-first minting, why confidence is
  never the LLM's self-report.
- `docs/raw-to-principles-research.md` — segmentation + rendering rationale.
- `docs/TIME_CAPSULE_FLYWHEEL.md` — the north-star vision (NOT built; don't
  confuse with the POC).
- `src/core/principle.py` — `Principle`/`Edge`/`LedgerRow` with their provenance
  guards. `src/pipeline/link.py` — rung ④ merge + typed edges.

---

## The pivots & decisions worth knowing (the "why it looks like this")

- **No re-embedding.** Memories keep Hindsight's own qwen vectors; we read them
  straight from pg0 (`memory_units.embedding`) rather than recomputing. Only a
  proposed principle's text is embedded (for the novelty check).
- **Clustering threshold = 0.78, not the engine default 0.55.** At 0.55,
  single-link clustering chains ~200 memories into one meaningless blob; 0.78
  gives coherent themes. If you re-tune, re-check the cluster-size distribution.
- **Principle quality is a prompt problem.** v1 produced a shallow "You value
  optimizing JSON compaction savings" from two *assistant* coding-session
  memories. Fix (see `_SYSTEM_PROMPT` in `propose.py`): demand the *enduring
  value* behind an activity and explicitly reject one-off tasks / tool-use /
  assistant-actions. v2 correctly returns `[]` for that cluster. The deeper fix
  (filtering assistant-subject memories before clustering) is **deferred**.
- **Confidence is ledger-derived, never the LLM's self-report** (RLHF makes
  verbalized confidence overconfident).
- **The current bank is partial & claude-skewed** — the live retain committed
  ~159 of 403 units before being stopped, so claude-chat dominates. Principles
  are real but lean digital/work-life. For a balanced demo, re-retain the full
  slice (use `retain_batch` — batched extract/embed for speed, transactional
  entity-merge for correctness; ~5–8 min vs ~45 min sequential).
- **Observability is mandatory for long runs** — a sequential retain once burned
  ~$11 showing zero progress because `print()` was block-buffered to a file. Now:
  background + log to a file, loguru on **stderr** (`2>&1`), per-item progress +
  ETA. This is a CLAUDE.md §6 convention.

## Known open work (for whoever picks it up)
- Rung ④ runner (`link_principles.py`) + a full merge/link run on the real bank.
- A principle → memory → raw-event **trace viewer** for the demo (only
  `show_bank.py` for memories exists).
- gemini-3.5-flash emits sloppy JSON during extraction (non-fatal retries +
  dropped causal links) — model/prompt iteration.
- Re-retain a balanced (non-claude-skewed) bank.

## Want your OWN principles? (the fact-check)

Run the one-shot bootstrap — empty checkout → your own principles, built from
YOUR data (iMessage + Photos read locally; drop Spotify/Claude exports in
`data/` if you have them). It retains only the **last 7 days** so it's cheap/fast:
```bash
bash scripts/bootstrap.sh --dry-run   # set up + build + show how many units (free)
bash scripts/bootstrap.sh             # full: build → retain 7d → mint → show your principles
```
Needs `uv`, `doppler` (logged in, berkeley-hackathon/dev access), and Full Disk
Access for your terminal (to read iMessage). Then read the principles it prints
and ask yourself: do these actually describe me? That's the fact-check.

## How to verify it works (have them run this — it's free)
```bash
PYTHONPATH=src .venv/bin/python -m pytest -q          # the suite
PYTHONPATH=src .venv/bin/python scripts/show_bank.py  # see memories → raw rows
cat data/principles.json                               # the principles
```
The live pipeline steps cost OpenRouter money — **always `--dry-run`/`--limit`
smoke first, and never run a paid step blind** (see `docs/PIPELINE_FLOW.md`).
