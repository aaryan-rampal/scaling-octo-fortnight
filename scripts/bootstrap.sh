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

DAYS="${DAYS:-7}"
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

# --- 3. build the unified events DB (enrich only the slice you'll retain) -----
log "Building data/recall.db (enriching the last $DAYS days — LIVE)"
$DOPPLER env PYTHONPATH=src "$PY" scripts/build_all_sources_db.py \
  --fresh --enrich-days "$DAYS" 2>&1 | tee /tmp/bootstrap_build.log
grep -q "Done. Unified store" /tmp/bootstrap_build.log \
  || die "Build did not finish cleanly — see /tmp/bootstrap_build.log"

if [[ -n "$DRY_RUN" ]]; then
  log "Dry-run: counting how many units the $DAYS-day slice would retain (no paid calls)"
  PYTHONPATH=src "$PY" - "$DAYS" <<'PY'
import sys
from collections import Counter
from datetime import timedelta
from pipeline.segment import segment_recent

units = segment_recent(window=timedelta(days=int(sys.argv[1])))
print(f"  would retain {len(units)} units (= LLM calls); by source: "
      f"{dict(Counter(u.source for u in units))}")
PY
  log "Dry-run complete. Re-run without --dry-run to mint your principles."
  exit 0
fi

# --- 4. retain the last N days into Hindsight (LIVE, ~70 units for 7 days) ----
log "Retaining the last $DAYS days into Hindsight bank slice-7d (LIVE — this takes a few minutes)"
$DOPPLER env PYTHONPATH=src "$PY" scripts/retain_slice.py --days "$DAYS" \
  2>&1 | tee /tmp/bootstrap_retain.log
grep -q "into bank" /tmp/bootstrap_retain.log \
  || die "Retain did not finish — see /tmp/bootstrap_retain.log"

# --- 5. mint principles (LIVE) -----------------------------------------------
log "Minting your principles (LIVE)"
$DOPPLER env PYTHONPATH=src "$PY" scripts/mint_principles.py \
  2>&1 | tee /tmp/bootstrap_mint.log
grep -q "done:" /tmp/bootstrap_mint.log || die "Mint did not finish — see /tmp/bootstrap_mint.log"

# --- 6. show them (the fact-check) -------------------------------------------
log "Your principles (fact-check these against yourself):"
PYTHONPATH=src "$PY" - <<'PY'
import json
from pathlib import Path
p = Path("data/principles.json")
ps = json.loads(p.read_text()) if p.exists() else []
print(f"\n  {len(ps)} principles → {p}\n")
for x in sorted(ps, key=lambda x: -x["confidence"]):
    print(f"  [{x['confidence']:.2f}] {x['text']}")
print("\n  Each cites >=2 of your memories (derived_from). Trace any one with:")
print("    PYTHONPATH=src .venv/bin/python scripts/show_bank.py --trace")
PY

log "Done. Do these describe you? That's the fact-check."
