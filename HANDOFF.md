# Handoff — raw→principles vertical (2026-06-21)

Branch `aaryan-principles`. This session took the pipeline from "principles engine
built but never run live" to **principles minted, linked, and a full end-to-end
traced run**. Below: what's done, what's committed vs not, the one open bug, and
the exact next steps.

---

## State at a glance

- **The whole pipeline runs end to end** and produces real, traceable principles.
- **Committed + pushed:** through `e6bfef9` is on origin. **3 commits are local-only
  (NOT pushed):** `a862524`, `cbe48a1`, `7388523`.
- **Working tree is DIRTY** (uncommitted) — the end-to-end run modified data files
  and applied a bug fix. See "Uncommitted changes" below before you commit.
- Tests: 264+ green at last full run (before the dirty changes; re-run to confirm).

---

## FIRST: deal with the uncommitted working tree

`git status` shows these modified/deleted, from the end-to-end run + a bug fix:

- `src/runtime/hindsight.py` — **a real fix, keep it:** bumped the Hindsight client
  HTTP timeout 300s→1800s (the retain bug below). Commit this.
- `src/pipeline/render.py`, `scripts/retain_slice.py`, `scripts/dump_bank.py` —
  the e2e subagent touched these (mostly the `RetainProgress` observability type).
  Review the diff; they're likely keepers but were not gate-checked by me post-edit.
- `data/principles.json` — **OVERWRITTEN** by the e2e run with a **claude-only,
  16-principle** set (from a partial bank — see bug). The earlier *good* 12-principle
  set is archived at `runs/2026-06-21T10-45Z/archived_prior/` and the e2e copy is
  `runs/2026-06-21T10-45Z/step5_mint.json`. Decide which you want as `data/principles.json`.
- `data/principles.v1.json` — **DELETED** by the run's archive step (moved into
  `runs/2026-06-21T10-45Z/archived_prior/`). Restore from there if you want it tracked again.

**Run `ruff check` + `pytest -q` before committing any of this** — I did not gate
the e2e subagent's edits to render.py/retain_slice.py/dump_bank.py.

---

## The one open bug (FIXED in working tree, not yet committed)

The end-to-end retain **timed out**: `hindsight_client.Hindsight` has a **300s default
HTTP request timeout**, and a 25-unit `retain_batch` chunk takes longer than that, so
chunk 1 aborted at 300.5s and chunks 2-5 cascaded. Only **13 of 119 units committed**
(all claude — the claude-heavy first chunk), so the e2e bank is **claude-only**.

The fix is already applied in `src/runtime/hindsight.py` (timeout → 1800s). To get a
**complete** bank, just re-run retain with the fix in place. Consider also a smaller
`--chunk-size` (e.g. 10) so each chunk stays well under any timeout.

---

## What got built this session (committed)

- **Rung ③ mint** (`src/pipeline/propose.py`, `scripts/mint_principles.py`) — live
  PrincipleProposer (gemini), clusters at **0.78** (default 0.55 single-link-chains
  the bank), no-re-embed (reads qwen vectors from pg0 `memory_units.embedding`).
  Prompt rejects one-off/tool/assistant memories (fixed a shallow "JSON compaction"
  principle).
- **Rung ④ link** (`src/pipeline/link.py`, `scripts/link_principles.py`) — merge
  near-dupes (cosine≥0.80, UNION provenance) + typed grounded edges (0.60–0.80 band).
- **retain_batch** (`scripts/retain_slice.py`, `render.py`) — chunked, ~3-8× faster
  than the old per-unit loop; per-item document_id preserves provenance.
- **Three-window model** — per-source INGEST windows in the build
  (`--imessage-days`/`--photos-days`/`--spotify-days`/`--claude-days`, default `--days`);
  enrichment applies to whatever's ingested; **retain defaults to the WHOLE db**
  (`segment_recent` window now optional; `retain_slice --days 0` = all). Ingest is the
  single source of truth for scope.
- **Observability** (`src/core/logging.py`) — loguru, flushed **stderr** (capture with
  `2>&1`, never bare `>`). Wired into build + retain + mint.
- **Teammate onboarding** — `scripts/bootstrap.sh` (empty checkout → own principles),
  `PROMPT.md`, `docs/PIPELINE_FLOW.md`.

## The end-to-end traced run — `runs/2026-06-21T10-45Z/`

`step1..6` JSON artifacts + `RUN_FLOW.md` (read this for the full trace). Headlines:
- build: 956 events (7d, per-source windows), photo vision 10/32 (local-thumbnail limit).
- retain: **PARTIAL** (the timeout bug) — 13/119 units, 407 memories, claude-only.
- dump_bank: 407/407 provenance (100%).
- mint: 16 principles, 18 clusters @0.78, confidence 0.50–0.75 (all claude — partial bank).
- link: 7 edges (supports/refines).

---

## NEXT STEPS (in order)

1. **Resolve the working tree** (above): keep the hindsight.py timeout fix, review the
   e2e edits, decide which `data/principles.json` you want, restore `principles.v1.json`
   if wanted. Run gates. Commit.
2. **Push the 3 local commits** (`a862524`, `cbe48a1`, `7388523`) + the new commit.
3. **Re-run retain to completion** now that the 300s timeout is fixed → full
   (non-claude-only) bank → re-mint → balanced principles. Use the e2e run as the recipe
   (`RUN_FLOW.md`), or just `retain_slice.py` (whole db) then `mint_principles.py`.
4. **Full rung-④ link run** on the complete bank (current edges are from the partial bank).

## Gotchas / decisions locked

- Run via `PYTHONPATH=src .venv/bin/python`; LIVE steps need Doppler
  (`--project berkeley-hackathon --config dev`). DB reads: Python sqlite3, not the CLI.
- No re-embedding memories — pg0 `memory_units.embedding`, password `hindsight`.
- Clustering threshold **0.78**. Only ONE embedded Hindsight (pg0 :5432) at a time.
- `data/` is gitignored; principles JSONs were force-added (`git add -f`).
- Per-source ingest windows are relative to **each source's own latest event** — claude's
  local export ends 2026-05-28, so its 7d window is late May, not mid-June (noted in
  `runs/.../step2_build.json`).
