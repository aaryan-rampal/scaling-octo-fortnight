# Handoff — raw→principles vertical (mobile → Mac)

Written 2026-06-21. Branch `aaryan-principles`. You (Aaryan) are switching from
mobile back to your Mac to keep coding. This is what's done, what's running, and
the exact next steps. **Principles are the priority — your team is blocked on
them.**

---

## FIRST THING: check the background rebuild

A full `recall.db` rebuild is running in the background (backgrounded task
`b5b4p6ukp`, log at `/tmp/recall_build2.log`). **Check it directly:**

```bash
pgrep -f build_all_sources_db && echo RUNNING || echo DONE
cat /tmp/recall_build2.log
```

- If still RUNNING: imessage chat.db decode is the slow part (~minutes of silence
  before first output). Let it finish.
- When DONE, the log ends with `Done. Unified store at data/recall.db (<N> events)`.

**Verify the rebuild (don't trust exit code — last run had two real bugs we only
caught by verifying):**

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import sqlite3, json
con = sqlite3.connect("data/recall.db")
mx, = con.execute("SELECT MAX(t_utc) FROM events").fetchone()
print("by source:", dict(con.execute("SELECT source, COUNT(*) FROM events GROUP BY source")))
for src,key in [("imessage","contact_name"),("photos","vision_description"),("spotify","artist_vibe")]:
    rows=con.execute("SELECT additional_data FROM events WHERE source=? AND t_utc>=datetime(?,'-30 days')",(src,mx)).fetchall()
    have=sum(1 for (ad,) in rows if json.loads(ad or '{}').get(key))
    print(f"{src}: {have}/{len(rows)} slice rows have {key}")
con.close()
PY
```

Expect: imessage `contact_name` ~all; spotify `artist_vibe` ~all; **photos
`vision_description` >0 (~28 — the proof the thumbnail fallback worked)**. Spotify
total should be back near ~123k (not 192k — the min_ms_played filter is fixed).

---

## What's committed (working tree clean, NOT pushed — user said no push yet)

- `8a41ddd` feat(render): enrichment scalar allowlist (contact_name/vision/vibe)
- `d8c596a` feat(photos): vision via local thumbnails + slice-enriching rebuild
  script + spotify min_ms_played fix
- `87d33a3` feat(mint): rung 3 principle schema + cluster-first minting

**191 tests pass, ruff + ty clean.** Run: `PYTHONPATH=src .venv/bin/python -m pytest -q`

---

## The principle engine is BUILT and tested — only the LLM seam is missing

`src/pipeline/mint.py` (rung ③, cluster-first per `docs/rung3-minting-strategy.md`)
has all the deterministic, grounded pieces done + unit-tested:
- `cluster_memories` (embedding similarity, singletons dropped)
- `compute_confidence` (ledger formula, never the LLM)
- `verify_citations` (non-LLM: cited id must be in the cluster shown)
- `is_novel` (embedding restatement guard)
- `mint_principles` orchestrator
- The one stochastic step is behind the `PrincipleProposer` Protocol (injectable,
  faked in tests) — mirrors how `render.py` does `RetainClient`.

`src/core/principle.py` has the pinned `Principle` / `Edge` / `LedgerRow` types
with the ≥2-supports / ≥1-edge provenance guards.

---

## NEXT STEPS to get principles live (in order, your critical path)

1. **Re-retain the enriched slice into Hindsight** (LIVE, OpenRouter):
   ```bash
   doppler run --project berkeley-hackathon --config dev -- \
     env PYTHONPATH=src .venv/bin/python scripts/retain_slice.py --days 30
   ```
   Note: `retain_slice.py` uses bank `slice-7d` and `--days` default 7 — bump to
   30 to match the enrich window, or it retains a narrower slice than we enriched.

2. **Write `scripts/dump_bank.py`** — THIS GAP STILL EXISTS. Nothing in the repo
   writes `data/bank_snapshot.json`; the prior agent did it ad-hoc. Needed for EDA
   + show_bank. It should read bank `slice-7d` from Hindsight and emit the 9-field
   shape EDA expects: `memory_id, text, document_id, source, tags, entities,
   occurred_start, fact_type, raw_events[]`. (See an existing snapshot's shape in
   `data/archive/2026-06-21_pre-enrichment-wiring/bank_snapshot.pre-enrichment-wiring.json`.)

3. **Re-run EDA + compare** against the archived baseline:
   ```bash
   PYTHONPATH=src .venv/bin/python scripts/eda_bank.py
   ```
   Compare `docs/eda-findings.md` vs
   `data/archive/2026-06-21_pre-enrichment-wiring/eda-findings.pre-enrichment-wiring.md`.
   Key question: **did photos go from 0.00 specific entities to non-zero?** (vision
   descriptions should add real entities — the headline EDA win).

4. **Write the live `PrincipleProposer`** — a thin OpenRouter (gemini-3.5-flash)
   adapter implementing `propose(cluster) -> [(text, [memory_id,...])]`, plus a
   `MemoryCard` adapter mapping a live Hindsight `recall()` result (with its qwen
   embedding — DO NOT re-embed) into `mint.MemoryCard`. Then a runner script that
   recalls the bank → `mint_principles(...)` → writes principles. This is the last
   piece; the engine already works.

---

## Gotchas / decisions locked

- **Run via `PYTHONPATH=src .venv/bin/python`** — package is NOT installed by design.
- **DB reads: use Python sqlite3**, not the `sqlite3` CLI (hangs in this shell).
- **Photo vision = local thumbnails only** (~28 in 30d). Full iCloud coverage is
  DEFERRED (see memory `photo-vision-icloud-coverage`). download→delete doesn't
  work cleanly on a managed Photos library.
- **No re-embedding** — use Hindsight's own qwen vectors from `recall()`.
- **Enrich window = 30 days** (was 7) for more demo photos.
- Archived baseline (pre-enrichment) is in
  `data/archive/2026-06-21_pre-enrichment-wiring/` (old bank, old EDA, old recall.db).
- Rung ④ (typed edges) deferred — user confirmed edges SHOULD be typed; the link
  doc looked outdated, leave link.py for after rung ③ runs on the real bank.
