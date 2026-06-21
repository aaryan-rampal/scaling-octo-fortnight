# Handoff brief — for the teammate's Claude (Opus)

You are a Claude Code (Opus) agent on a teammate's laptop. Another Claude built
the changes described here on the `aaryan-principles` branch. Your job: **pull
them, understand what's new, verify it works using only the FREE checks below,
and STOP before any step that spends OpenRouter.** Do not run a paid pipeline
step unless the user explicitly tells you to.

Read the files yourself before explaining — trust the disk over this doc if they
disagree, and say so.

---

## 0. The hard rule: stop before spend

These three scripts make **paid OpenRouter calls** (LLM extraction / embedding /
proposal). Do NOT run them during verification:

- `scripts/retain_slice.py` (gemini extraction + qwen embedding per unit)
- `scripts/mint_principles.py` (LLM principle proposer)
- `scripts/link_principles.py` (LLM edge proposer + embeddings)

`scripts/build_all_sources_db.py` also spends a little (photo-vision / Spotify-vibe
enrichment on cache misses). The full run is driven by `scripts/bootstrap.sh`;
**`bash scripts/bootstrap.sh --dry-run` sets up + segments and `exit 0`s BEFORE
the first paid call** — that is your safe stop line. Everything in §3 is free.

---

## 1. Pull the changes

```bash
git fetch origin
git checkout aaryan-principles
git pull --ff-only origin aaryan-principles
```

New commits to expect (most recent first):

| commit | what it adds |
|---|---|
| `feat(segment): stratify sources at raw->Hindsight, ON by default` | the headline — see §2.1 |
| `feat(link): capture merge/link intermediate steps to a display-only sidecar` | §2.2 |
| `feat(scripts): build full-recall traceable recall_expansive.db` | §2.3 |
| `fix(bootstrap): run dump before link so the provenance trace connects` | §2.4 |
| earlier: parallelized adapters, Sentry everywhere, demo viz | context |

---

## 2. What's new

### 2.1 Source stratification (the important one) — `src/pipeline/segment.py`

**Problem it fixes:** the raw DB has every source, but claude conversations are
huge (~49 events/unit), so Hindsight extracted ~92% claude memories and principles
skewed claude. **Fix:** `_stratify_by_source_budget` caps the EVENTS any single
source contributes (largest units first, whole units only — provenance intact),
applied after the weekly quota. Thin sources below the floor are kept whole and
logged, never inflated.

It is **ON by default**: `retain_slice.py --source-event-ceiling` defaults to
`1000`; `bootstrap.sh` passes it (override via `CEILING=`). On the original data
this rebalances claude `2256 -> 997` events, even with imessage `989` /
spotify `951`. This prunes BEFORE extraction spend — it changes what gets retained.

### 2.2 Merge/link trace capture — `src/pipeline/link.py`

`run_merge` / `run_linking` take an optional `PipelineTrace` (default `None` = no
behaviour change) recording each merge group (survivor + absorbed pre-merge
principles) and each considered link pair (ids + cosine + relation).
`link_principles.py` writes it to `data/link_trace.json`, flagged `display_only`.
**The absorbed pre-merge principles are display-only — never in recall.db, never
traceable.** This feeds the demo viz's forward-pass animation.

### 2.3 `recall_expansive.db` builder — `scripts/build_expansive_db.py`

Builds a SEPARATE `data/recall_expansive.db` by clustering ALL ~3458 pg0 memories
(bypassing the capped `recall()` the normal mint uses, which only sees ~111). It
mints every cluster and materialises the full traceable ladder. **PAID + long
(~45-90 min, ~$5-10).** Don't run it to verify; just know it exists.

### 2.4 Provenance ordering fix — `scripts/bootstrap.sh`

`dump` (memory layer) now runs BEFORE `link` (principle layer). `link` writes
`principle_memories`, whose rows FK-reference `memories`; running link first left
that table empty and silently broke the principle->memory->raw trace. Step 8 is
now a HARD GATE that exits non-zero if any principle fails to reach raw events.

---

## 3. Verify it works — FREE checks only (no OpenRouter)

Run these from the repo root. All are offline / read-only.

```bash
# 3a. env (repo convention: ~/env/recall symlinked as .venv)
.venv/bin/python -V          # expect 3.13

# 3b. tests + lint + types — should all be green
PYTHONPATH=src .venv/bin/python -m pytest -q        # expect ~281 passed
.venv/bin/ruff check src/ scripts/
.venv/bin/ty check src/pipeline/segment.py src/pipeline/link.py
```

```bash
# 3c. PROVE the stratification works (reads recall.db, NO LLM) — the headline.
# Shows events-per-source WITHOUT vs WITH the default ceiling=1000.
PYTHONPATH=src .venv/bin/python - <<'PY'
from collections import defaultdict
from datetime import timedelta
from pipeline.segment import segment_windowed_quota

def ev(units):
    d = defaultdict(int)
    for u in units:
        d[u.source] += len(u.derived_from)
    return dict(d)

base = segment_windowed_quota(span=timedelta(days=90), interval=timedelta(days=7),
                              per_interval=9, min_imessage_msgs=20)             # ceiling off
strat = segment_windowed_quota(span=timedelta(days=90), interval=timedelta(days=7),
                               per_interval=9, min_imessage_msgs=20,
                               source_event_ceiling=1000, source_event_floor=200)  # default
print("NO ceiling :", ev(base))      # claude dominates
print("ceiling=1000:", ev(strat))    # claude capped, sources even
PY
# PASS = claude's event count drops to roughly match the other sources.
# (Exact numbers depend on this laptop's own data; the SHAPE is what matters.)
```

```bash
# 3d. bootstrap dry-run — sets up + segments, STOPS before any paid call.
#     Confirms wiring end-to-end without spending. Needs Doppler only for env;
#     it exits 0 before the first OpenRouter call.
bash scripts/bootstrap.sh --dry-run
# expect: source/unit counts printed, then "Dry-run complete" and exit 0.
```

```bash
# 3e. the demo viz (TypeScript, no LLM) — optional, visual.
cd backend_viz && pnpm install && pnpm typecheck && pnpm dev   # http://localhost:5600
# forward/backward modes; reads public/demo_data.json (already committed).
```

If `data/link_trace.json` exists it's display-only viz data; if not, the viz falls
back to an illustrative merge (clearly labeled) — both fine for verification.

---

## 4. STOP HERE

That is the full free verification. **Do not run `retain_slice.py`,
`mint_principles.py`, `link_principles.py`, `build_expansive_db.py`, or a full
`bootstrap.sh` (without `--dry-run`)** unless the user explicitly asks — those
spend OpenRouter. When they're ready for a real run, the recipe is in
`scripts/bootstrap.sh` (prereqs: Doppler access to `berkeley-hackathon/dev`,
macOS Full Disk Access for iMessage). Report what passed/failed in §3 and wait.
