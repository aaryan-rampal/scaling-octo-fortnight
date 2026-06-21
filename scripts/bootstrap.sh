#!/usr/bin/env bash
# bootstrap.sh — empty checkout → your own principles, for fact-checking.
#
# Run this on YOUR Mac after checking out the aaryan-principles branch. It builds
# a memory bank from YOUR OWN data (iMessage + Photos are read locally; drop
# Spotify/Claude exports in data/ if you have them), retains the LAST 7 DAYS into
# Hindsight, mints principles, and shows them to you so you can sanity-check
# whether the engine describes you accurately.
#
# Prereqs: uv, doppler (brew install doppler), Doppler access to the
# berkeley-hackathon/dev project, and macOS Full Disk Access for your terminal
# (so it can read ~/Library/Messages/chat.db). LIVE: spends OpenRouter on the
# 7-day slice (~70 units of gemini extraction + qwen embedding).
#
# Usage:
#   bash scripts/bootstrap.sh              # full run
#   DAYS=14 bash scripts/bootstrap.sh      # widen the window
#   bash scripts/bootstrap.sh --dry-run    # set up + build + segment counts, NO paid calls

set -euo pipefail

# Ingest reach (days). 90 gives the temporal sampler real history to span; the
# quota keeps retain cost ~30-days-worth regardless. Override with DAYS=.
DAYS="${DAYS:-90}"
# Spotify enrichment is the one slow-on-cache-miss source; cap its window so a
# fresh teammate isn't paying for a 90-day artist tail. Override with SPOTIFY_DAYS=.
SPOTIFY_DAYS="${SPOTIFY_DAYS:-30}"
# Quota K: units kept per weekly bucket by the temporal-spread sampler.
QUOTA="${QUOTA:-9}"
DOPPLER="doppler run --project berkeley-hackathon --config dev --"
PY=".venv/bin/python"
DRY_RUN=""
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN="1"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. prereqs --------------------------------------------------------------
log "Checking prerequisites"
command -v uv >/dev/null || die "uv not found. Install: https://docs.astral.sh/uv/"
command -v doppler >/dev/null || die "doppler not found. Install: brew install doppler"
doppler configure get token >/dev/null 2>&1 || doppler whoami >/dev/null 2>&1 \
  || die "Doppler not logged in. Run: doppler login"
[[ -f pyproject.toml ]] || die "Run this from the repo root (pyproject.toml not found)."

# --- 1. venv (repo convention: ~/env/recall symlinked as .venv) --------------
if [[ ! -d .venv ]]; then
  log "Creating uv venv at ~/env/recall and symlinking .venv"
  uv venv ~/env/recall --python 3.13
  ln -s ~/env/recall .venv
fi
log "Installing the package (editable)"
uv pip install --python "$PY/../python" -e . >/dev/null 2>&1 \
  || uv pip install --python "$PY" -e .

# --- 2. source check (build reads what you have; missing sources are OK) ------
log "Checking your local data sources"
[[ -f "$HOME/Library/Messages/chat.db" ]] \
  && echo "  iMessage: found" \
  || echo "  iMessage: NOT found (grant Full Disk Access, or it'll be skipped)"
ls "$HOME/Pictures/Photos Library.photoslibrary/database/Photos.sqlite" >/dev/null 2>&1 \
  && echo "  Photos: found" || echo "  Photos: NOT found (will be skipped)"
if compgen -G "data/spotify_export/*.json" >/dev/null 2>&1; then
  echo "  Spotify: export present"
else
  echo "  Spotify: no export in data/spotify_export (optional)"
fi
[[ -f data/claude_export/conversations.json ]] \
  && echo "  Claude: export present" \
  || echo "  Claude: no export in data/claude_export (optional)"

# --- 3. build the unified events DB (per-source ingest windows) --------------
log "Building data/recall.db (ingesting last ${DAYS}d, spotify ${SPOTIFY_DAYS}d — LIVE)"
$DOPPLER env PYTHONPATH=src "$PY" scripts/build_all_sources_db.py \
  --fresh --days "$DAYS" --spotify-days "$SPOTIFY_DAYS" 2>&1 | tee /tmp/bootstrap_build.log
grep -q "Done. Unified store" /tmp/bootstrap_build.log \
  || die "Build did not finish cleanly — see /tmp/bootstrap_build.log"

if [[ -n "$DRY_RUN" ]]; then
  log "Dry-run: counting how many units the quota sampler would retain (no paid calls)"
  PYTHONPATH=src "$PY" - "$QUOTA" <<'PY'
import sys
from collections import Counter
from datetime import timedelta
from pipeline.segment import segment_windowed_quota

units = segment_windowed_quota(
    span=timedelta(days=90), interval=timedelta(days=7), per_interval=int(sys.argv[1])
)
print(f"  would retain {len(units)} units (= LLM calls); by source: "
      f"{dict(Counter(u.source for u in units))}")
PY
  log "Dry-run complete. Re-run without --dry-run to mint your principles."
  exit 0
fi

# --- 4. retain via the temporal-spread sampler (LIVE) ------------------------
# The quota sampler reaches 90 days back but keeps only ~K units per week, so
# retain cost stays ~30-days-worth while principles draw on real history.
log "Retaining into Hindsight bank slice-7d (quota sampler, K=$QUOTA — LIVE, a few minutes)"
$DOPPLER env PYTHONPATH=src "$PY" scripts/retain_slice.py \
  --quota "$QUOTA" --span-days 90 --interval-days 7 --min-imessage-msgs 20 \
  2>&1 | tee /tmp/bootstrap_retain.log
grep -q "into bank" /tmp/bootstrap_retain.log \
  || die "Retain did not finish — see /tmp/bootstrap_retain.log"

# --- 5. mint principles (LIVE) -----------------------------------------------
log "Minting your principles (LIVE)"
$DOPPLER env PYTHONPATH=src "$PY" scripts/mint_principles.py \
  2>&1 | tee /tmp/bootstrap_mint.log
grep -q "done:" /tmp/bootstrap_mint.log || die "Mint did not finish — see /tmp/bootstrap_mint.log"

# --- 6. link: merge near-dupes + typed edges -> recall.db principle layer -----
log "Linking principles (merge near-dupes + grounded edges) — writes recall.db"
$DOPPLER env PYTHONPATH=src "$PY" scripts/link_principles.py \
  2>&1 | tee /tmp/bootstrap_link.log
grep -q "edges" /tmp/bootstrap_link.log || die "Link did not finish — see /tmp/bootstrap_link.log"

# --- 7. dump: materialise the memory layer + raw provenance -> recall.db ------
# --days 0 re-segments the whole DB (a superset of the sampled units), so every
# retained memory resolves its raw events; dangling units simply go unmatched.
log "Materialising the memory->raw provenance into recall.db"
$DOPPLER env PYTHONPATH=src "$PY" scripts/dump_bank.py --days 0 \
  2>&1 | tee /tmp/bootstrap_dump.log
grep -q "memory records into" /tmp/bootstrap_dump.log \
  || die "Dump did not finish — see /tmp/bootstrap_dump.log"

# --- 8. show + verify the traceable recall.db (the fact-check) ----------------
log "Your principles, now traceable to raw data in recall.db:"
PYTHONPATH=src "$PY" - <<'PY'
import sqlite3
c = sqlite3.connect("data/recall.db")
n = lambda t: c.execute(f"select count(*) from {t}").fetchone()[0]
print(f"\n  {n('principles')} principles · {n('edges')} edges · "
      f"{n('memories')} memories · {n('events')} raw events\n")
for text, conf in c.execute(
    "select text, confidence from principles order by confidence desc"
):
    print(f"  [{conf:.2f}] {text}")
reach = c.execute(
    "select count(distinct pm.principle_id) from principle_memories pm "
    "join memory_events me on me.memory_id = pm.memory_id"
).fetchone()[0]
print(f"\n  {reach}/{n('principles')} principles trace to >=1 raw event. "
      "Walk any one: principle -> principle_memories -> memory_events -> events.")
PY

log "Done. Principles minted, linked, and traceable to your raw data in recall.db."
