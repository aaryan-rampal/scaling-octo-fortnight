"""One-off: retain the 7-day slice into a Hindsight bank (rung ① → ② live).

Segments the trailing 7 days of ``data/recall.db`` into units, renders each to
text, and retains it into an embedded Hindsight bank. This is the first LIVE run
(spends OpenRouter: gemini extraction + qwen embeddings per unit), so it supports
``--limit`` to do a cheap small batch first and surface issues before the full
slice.

Run (Doppler injects OPENROUTER_API_KEY):
    doppler run --project berkeley-hackathon --config dev -- \
        env PYTHONPATH=src .venv/bin/python scripts/retain_slice.py --limit 5
"""

from __future__ import annotations

import argparse
import contextlib
from collections import Counter
from datetime import timedelta

from pipeline.render import render_unit, retain_unit
from pipeline.segment import segment_recent
from runtime.hindsight import embedded_hindsight
from storage.store import CapsuleStore

BANK = "slice-7d"


def _unit_author_role(unit, events_by_id: dict) -> str | None:
    """Pick a representative author_role for a unit's network routing.

    Conversational units mix self/other; route by whichever role authored more of
    the unit's events (ties → "self"). Non-conversational units have no role.
    """
    roles = [events_by_id[i].author_role for i in unit.derived_from if i in events_by_id]
    roles = [r for r in roles if r]
    if not roles:
        return None
    counts = Counter(roles)
    return "self" if counts["self"] >= counts["other"] else "other"


def main() -> None:
    """Segment + render + retain the slice, reporting progress and any failures."""
    ap = argparse.ArgumentParser(description="Retain the 7-day slice into Hindsight.")
    ap.add_argument("--limit", type=int, default=0, help="Max units to retain (0 = all).")
    ap.add_argument("--days", type=int, default=7, help="Trailing window in days.")
    args = ap.parse_args()

    units = segment_recent(window=timedelta(days=args.days))
    print(f"segmented {len(units)} units; by source: {dict(Counter(u.source for u in units))}")
    if args.limit:
        units = units[: args.limit]
        print(f"limiting to first {len(units)} units")

    events_by_id = {e.id: e for e in CapsuleStore().list_events()}

    retained, skipped, failed = 0, 0, 0
    with embedded_hindsight() as client:
        with contextlib.suppress(Exception):
            client.create_bank(bank_id=BANK)
        for i, unit in enumerate(units, 1):
            events = [events_by_id[j] for j in unit.derived_from if j in events_by_id]
            text = render_unit(unit, events)
            if not text.strip():
                skipped += 1
                continue
            role = _unit_author_role(unit, events_by_id)
            try:
                retain_unit(client, unit, text, author_role=role, bank_id=BANK)
                retained += 1
                print(f"[{i}/{len(units)}] {unit.source:8s} role={role or '-':6s} ok")
            except Exception as exc:  # report and keep going
                failed += 1
                print(f"[{i}/{len(units)}] {unit.source} FAILED: {type(exc).__name__}: {exc}")

    print(f"\nretained={retained} skipped(empty)={skipped} failed={failed} into bank {BANK!r}")


if __name__ == "__main__":
    main()
