# Pipeline flow — raw data → principles (as built, 2026-06-21)

The end-to-end flow that actually runs today, on branch `aaryan-principles`. This
is the **reconstruction-first POC**: real personal data in → memory bank →
traceable one-line principles out. The flywheel/swarm (CLAUDE.md §3) is still
vision-only.

```
raw sources           recall.db            Hindsight bank        principles
(chat.db, photos,  →  (unified events,  →  slice-7d           →  data/principles.json
 spotify, claude)     enriched slice)      (memories + qwen      + data/edges.json
                                            embeddings in pg0)    (+ merged.json)
   build              segment+render        recall+pg0 read       cluster+propose
```

## The five steps (commands)

All run via `PYTHONPATH=src .venv/bin/python`; LIVE steps need Doppler
(`doppler run --project berkeley-hackathon --config dev -- env ...`).
**Long/paid steps run backgrounded + logged to a file (CLAUDE.md §6).** loguru
writes to **stderr** — capture with `2>&1`, never bare `> file`.

| # | Step | Script | Cost | Output |
|---|---|---|---|---|
| 0 | Build unified events DB | `scripts/build_all_sources_db.py --fresh --enrich-days 30` | LIVE (vision+vibe enrich on slice) | `data/recall.db` (~271k events) |
| 1 | Segment + render + retain | `scripts/retain_slice.py --days 30` | LIVE (gemini extract + qwen embed per unit) | Hindsight bank `slice-7d` |
| 2 | Snapshot the bank | `scripts/dump_bank.py` | free | recall.db `memories` + `memory_events` (memory layer; `--out` for a JSON snapshot, observability-only) |
| — | EDA over the snapshot | `scripts/eda_bank.py` | free | stdout |
| 3 | Mint principles (rung ③) | `scripts/mint_principles.py` | LIVE (gemini propose + qwen novelty embed per cluster) | `data/principles.json` (transient rung-③→④ handoff) |
| 4 | Merge + link (rung ④) | `scripts/link_principles.py` | LIVE | recall.db `principles` / `principle_memories` / `edges` / `edge_memories` (principle layer; `--emit-json` for JSON, observability-only) |

Each step has `--dry-run` / `--limit*` for a free or cheap smoke before the full
paid run. **Always smoke first.**

**DB-as-truth.** Steps 2 and 4 write recall.db directly via
`storage.principle_store.PrincipleStore`; a completed run leaves **no JSON at
rest** (only recall.db + raw exports). Dump owns the memory layer, link owns the
principle layer; each resets only its own derived tables in one transaction and
never touches `events` / `capsules` / `media`. `data/principles.json` is the one
transient file (mint → link handoff). `scripts/load_principles_db.py` remains as
a fallback that re-loads the JSON artifacts into the DB if they exist.

## What each rung does

- **Build (step 0):** four adapters (`src/adapters/*`) project each source → canonical
  `Event` → one unified `events` table (`storage/persist.py`). LLM enrichment
  (photo vision, spotify artist vibes) runs only on the trailing slice and is
  cached in `additional_data`. iMessage contact names resolve at ingest (no LLM).
- **Retain (rung ①②, step 1):** `segment.py` cuts events into inactivity-gap
  `Unit`s; `render.py` renders each unit → text and calls Hindsight `retain`
  (one gemini extraction + qwen embedding per unit). The durable provenance link
  is `memory.document_id == unit.unit_id`.
- **Mint (rung ③, step 3):** `mint.py` clusters recalled memories by embedding
  cosine (**threshold 0.78** — the default 0.55 single-link-chains everything),
  drops singletons, and a gemini `PrincipleProposer` proposes one-line principles
  citing ≥2 memory_ids per cluster. Non-LLM guards: citation verification
  (cited id must be in the cluster), novelty (not a paraphrase of one memory),
  and ledger-derived confidence (**never** the LLM's self-report).
- **Link (rung ④, step 4):** `link.py` merges near-duplicate principles
  (cosine ≥0.80, **unioning** their cited memories so none are dropped) then adds
  typed grounded `Edge`s (supports/refines/generalizes/contradicts) between
  related principles (cosine 0.60–0.80).

## The load-bearing invariant (CLAUDE.md §2)

Provenance is the path: a principle is traceable **because** it was consolidated
from memories extracted from raw rows. Every rung carries a non-empty
`derived_from` of ids; `dump_bank.py` proves the chain
(`memory → document_id → unit → raw Events`) end to end — last run: **1010/1010
memories traceable**.

## Key implementation facts

- **No re-embedding of memories.** Hindsight's own qwen vectors (2000-dim) are
  read straight from pg0: `postgresql://hindsight:hindsight@127.0.0.1:5432/hindsight`,
  table `memory_units`, column `embedding`, keyed by memory `id`. The only embed
  call is `embed_principle(text)` for the novelty check (a new string).
- **Observability** lives in `src/core/logging.py` (`configure_logging()`); every
  long-running script streams flushed per-item progress + ETA to stderr.
- **Current bank is partial/claude-skewed** — the retain committed ~159 of 403
  units before being stopped, so the bank leans toward claude-chat. Good enough
  for "one non-obvious traceable insight"; re-retain the full slice (via
  `retain_batch` for speed) for a balanced demo.
