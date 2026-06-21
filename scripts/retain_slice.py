"""One-off: retain the 7-day slice into a Hindsight bank (rung ① → ② live).

Segments the trailing 7 days of ``data/recall.db`` into units, renders each to
text, and retains it into an embedded Hindsight bank. This is the first LIVE run
(spends OpenRouter: gemini extraction + qwen embeddings per unit), so it supports
``--limit`` to do a cheap small batch first and surface issues before the full
slice.

Progress is emitted to **stderr** via loguru (auto-flushed per record, so it
appears live even when redirected). To capture both progress and errors in a
single log file, redirect stderr:

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/retain_slice.py --limit 5 \\
        2>&1 | tee retain.log

Or with stderr only:

    ... 2> retain.log

Run (Doppler injects OPENROUTER_API_KEY):
    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/retain_slice.py --limit 5
"""

from __future__ import annotations

import argparse
import contextlib
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from loguru import logger

from core.logging import configure_logging
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


@dataclass
class _Progress:
    """Running tallies and timing for the retain loop."""

    total: int
    retained: int = 0
    skipped: int = 0
    failed: int = 0
    _timed_units: int = field(default=0, repr=False)
    _total_sec: float = field(default=0.0, repr=False)

    def record_timed(self, elapsed: float) -> None:
        """Add one timed retain to the running average."""
        self._timed_units += 1
        self._total_sec += elapsed

    def avg_sec(self) -> float | None:
        """Average seconds per timed retain, or None if none have completed."""
        return self._total_sec / self._timed_units if self._timed_units else None

    def eta_sec(self, index: int) -> float | None:
        """Estimated seconds remaining after unit at 1-based ``index``."""
        avg = self.avg_sec()
        if avg is None:
            return None
        return (self.total - index) * avg

    def aggregate_line(self, index: int) -> str:
        """Return a one-line aggregate + ETA string for the current position."""
        avg = self.avg_sec()
        avg_str = f"{avg:.1f}s/unit" if avg is not None else "?s/unit"
        eta = self.eta_sec(index)
        eta_str = f"{eta:.0f}s" if eta is not None else "?"
        return (
            f"  -> retained={self.retained} skipped={self.skipped} failed={self.failed}"
            f" | avg={avg_str} ETA={eta_str}"
        )


def main() -> None:
    """Segment + render + retain the slice, reporting live progress and any failures."""
    configure_logging()

    ap = argparse.ArgumentParser(description="Retain the 7-day slice into Hindsight.")
    ap.add_argument("--limit", type=int, default=0, help="Max units to retain (0 = all).")
    ap.add_argument("--days", type=int, default=7, help="Trailing window in days.")
    args = ap.parse_args()

    units = segment_recent(window=timedelta(days=args.days))
    by_source = dict(Counter(u.source for u in units))
    logger.info("segmented {} units; by source: {}", len(units), by_source)
    if args.limit:
        units = units[: args.limit]
        logger.info("limiting to first {} units", len(units))

    logger.warning(
        "LIVE PAID RUN: {} OpenRouter calls (extraction + embeddings per unit)", len(units)
    )

    events_by_id = {e.id: e for e in CapsuleStore().list_events()}
    prog = _Progress(total=len(units))

    with embedded_hindsight() as client:
        with contextlib.suppress(Exception):
            client.create_bank(bank_id=BANK)
        for i, unit in enumerate(units, 1):
            events = [events_by_id[j] for j in unit.derived_from if j in events_by_id]
            text = render_unit(unit, events)
            if not text.strip():
                prog.skipped += 1
                logger.debug("[{}/{}] {} skipped (empty render)", i, len(units), unit.source)
                continue
            role = _unit_author_role(unit, events_by_id)
            t0 = time.perf_counter()
            try:
                retain_unit(client, unit, text, author_role=role, bank_id=BANK)
                elapsed = time.perf_counter() - t0
                prog.retained += 1
                prog.record_timed(elapsed)
                logger.info(
                    "[{}/{}] {} role={} ok ({:.1f}s)",
                    i,
                    len(units),
                    unit.source,
                    role or "-",
                    elapsed,
                )
            except Exception as exc:  # report and keep going
                elapsed = time.perf_counter() - t0
                prog.failed += 1
                prog.record_timed(elapsed)
                logger.error(
                    "[{}/{}] {} FAILED ({:.1f}s): {}: {}",
                    i,
                    len(units),
                    unit.source,
                    elapsed,
                    type(exc).__name__,
                    exc,
                )
            logger.info("{}", prog.aggregate_line(i))

    logger.info(
        "\nretained={} skipped(empty)={} failed={} into bank {!r}",
        prog.retained,
        prog.skipped,
        prog.failed,
        BANK,
    )


if __name__ == "__main__":
    main()
