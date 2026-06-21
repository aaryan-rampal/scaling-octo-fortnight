"""One-off: retain ``data/recall.db`` into a Hindsight bank (rung ① → ② live).

Segments the store into units (the whole DB by default — the ingest step already
bounds what lands there; pass ``--days N`` only to retain a narrower sub-slice),
renders each to text, and retains them into an embedded Hindsight bank in chunks
of
:data:`CHUNK_SIZE` units per ``retain_batch`` call.  Batching eliminates the
sequential round-trip overhead of the old per-unit loop (~7 s idle per unit)
while each chunk boundary gives visible progress and limits the blast radius of
a single network failure.

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

import sentry_sdk
from loguru import logger

from core.logging import configure_logging
from observability.sentry import capture_exception, init_sentry, set_measurement
from pipeline.render import (
    RetainProgress,
    build_batch_item,
    render_unit,
    retain_batch_units,
)
from pipeline.segment import segment_recent, segment_windowed_quota
from runtime.hindsight import embedded_hindsight
from storage.store import CapsuleStore

BANK = "slice-7d"

#: Units per ``retain_batch`` call. The server extracts facts from all N units
#: concurrently (``asyncio.gather`` in ``extract_facts_from_contents``), then
#: entity-resolves in one transaction — so bigger chunks = more parallelism.
#: The counter-force is OpenRouter's per-minute rate limit: firing too many
#: extractions at once risks 429s and retry back-off that erases the gain.
#: 25 is a practical balance: ~25 concurrent extractions per chunk, chunks run
#: sequentially so the rate limiter sees a burst then a gap, and a failed chunk
#: loses at most 25 units. Tune up (50) if 429s are absent; tune down if they
#: appear in the logs.
CHUNK_SIZE = 25


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
    _timed_chunks: int = field(default=0, repr=False)
    _total_sec: float = field(default=0.0, repr=False)

    def record_timed(self, elapsed: float) -> None:
        """Add one timed chunk to the running average."""
        self._timed_chunks += 1
        self._total_sec += elapsed

    def avg_sec_per_unit(self) -> float | None:
        """Average seconds per retained unit, or None if none have completed."""
        if self._timed_chunks == 0 or self.retained == 0:
            return None
        return self._total_sec / self.retained

    def eta_sec(self, processed: int) -> float | None:
        """Estimated seconds remaining after ``processed`` units."""
        avg = self.avg_sec_per_unit()
        if avg is None:
            return None
        remaining = self.total - processed - self.skipped
        return max(remaining, 0) * avg

    def aggregate_line(self, processed: int) -> str:
        """Return a one-line aggregate + ETA string for the current position."""
        avg = self.avg_sec_per_unit()
        avg_str = f"{avg:.2f}s/unit" if avg is not None else "?s/unit"
        eta = self.eta_sec(processed)
        eta_str = f"{eta:.0f}s" if eta is not None else "?"
        return (
            f"  -> retained={self.retained} skipped={self.skipped} failed={self.failed}"
            f" | avg={avg_str} ETA={eta_str}"
        )


def main() -> None:
    """Segment + render + retain the slice, reporting live progress and any failures."""
    configure_logging()
    init_sentry(component="retain")

    ap = argparse.ArgumentParser(description="Retain recall.db into Hindsight.")
    ap.add_argument("--limit", type=int, default=0, help="Max units to retain (0 = all).")
    ap.add_argument(
        "--days",
        type=int,
        default=0,
        help="Optional trailing window in days; 0 (default) retains the whole DB "
        "(ingest already bounds what's there).",
    )
    ap.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Units per retain_batch call (default {CHUNK_SIZE}).",
    )
    ap.add_argument(
        "--quota",
        type=int,
        default=0,
        help="Opt in to the temporal-spread sampler: units kept per interval (K). "
        "0 (default) uses the contiguous segment_recent path unchanged.",
    )
    ap.add_argument(
        "--span-days",
        type=int,
        default=90,
        help="Reach (days) for the quota sampler; only used with --quota.",
    )
    ap.add_argument(
        "--interval-days",
        type=int,
        default=7,
        help="Bucket width (days) for the quota sampler; only used with --quota.",
    )
    ap.add_argument(
        "--min-imessage-msgs",
        type=int,
        default=20,
        help="Min source events for an iMessage unit to survive the gate "
        "(quota sampler only).",
    )
    ap.add_argument(
        "--source-event-ceiling",
        type=int,
        default=1000,
        help="Cap events any one source contributes, so a dense source (claude) "
        "doesn't dominate Hindsight's memories. ON by default (1000); pass 0 to "
        "disable stratification.",
    )
    ap.add_argument(
        "--source-event-floor",
        type=int,
        default=200,
        help="Min events we'd like per source; below it a warning is logged "
        "(only used with --source-event-ceiling).",
    )
    args = ap.parse_args()

    if args.quota > 0:
        units = segment_windowed_quota(
            span=timedelta(days=args.span_days),
            interval=timedelta(days=args.interval_days),
            per_interval=args.quota,
            min_imessage_msgs=args.min_imessage_msgs,
            source_event_ceiling=args.source_event_ceiling,
            source_event_floor=args.source_event_floor,
        )
    else:
        window = timedelta(days=args.days) if args.days > 0 else None
        units = segment_recent(window=window)
    by_source = dict(Counter(u.source for u in units))
    logger.info("segmented {} units; by source: {}", len(units), by_source)
    if args.limit:
        units = units[: args.limit]
        logger.info("limiting to first {} units", len(units))

    logger.warning(
        "LIVE PAID RUN: ~{} OpenRouter extraction calls (batched in chunks of {})",
        len(units),
        args.chunk_size,
    )

    transaction = sentry_sdk.start_transaction(op="retain", name="retain_slice")
    transaction.__enter__()
    set_measurement("units_segmented", len(units), "none")
    for source, count in by_source.items():
        set_measurement(f"units_{source}", count, "none")

    events_by_id = {e.id: e for e in CapsuleStore().list_events()}
    prog = _Progress(total=len(units))

    # --- render phase (no LLM, fast) ---
    rendered: list[tuple] = []  # (unit, text, role)
    for unit in units:
        events = [events_by_id[j] for j in unit.derived_from if j in events_by_id]
        text = render_unit(unit, events)
        if not text.strip():
            prog.skipped += 1
            logger.debug("skip {} (empty render)", unit.source)
            continue
        role = _unit_author_role(unit, events_by_id)
        rendered.append((unit, text, role))

    logger.info(
        "rendered {} units ({} skipped empty); batching in chunks of {}",
        len(rendered),
        prog.skipped,
        args.chunk_size,
    )

    # --- batch retain phase (LLM, network) ---
    with embedded_hindsight() as client:
        with contextlib.suppress(Exception):
            client.create_bank(bank_id=BANK)

        chunk_count = (len(rendered) + args.chunk_size - 1) // args.chunk_size
        total_events = sum(len(u.derived_from) for u, _, _ in rendered)
        units_done = 0
        events_done = 0
        for chunk_idx in range(chunk_count):
            chunk = rendered[chunk_idx * args.chunk_size : (chunk_idx + 1) * args.chunk_size]
            items = [build_batch_item(u, text, author_role=role) for u, text, role in chunk]
            chunk_events = sum(len(u.derived_from) for u, _, _ in chunk)
            chunk_progress = RetainProgress(
                units_done=units_done,
                units_total=len(rendered),
                events_done=events_done,
                events_total=total_events,
                chunk_units=len(chunk),
                chunk_events=chunk_events,
            )
            chunk_start = time.perf_counter()
            try:
                retain_batch_units(client, items, bank_id=BANK, progress=chunk_progress)
                elapsed = time.perf_counter() - chunk_start
                prog.retained += len(chunk)
                units_done += len(chunk)
                events_done += chunk_events
                prog.record_timed(elapsed)
                logger.info(
                    "[chunk {}/{}] {} units ok ({:.1f}s)",
                    chunk_idx + 1,
                    chunk_count,
                    len(chunk),
                    elapsed,
                )
            except Exception as exc:
                elapsed = time.perf_counter() - chunk_start
                prog.failed += len(chunk)
                prog.record_timed(elapsed)
                capture_exception(exc, context={"stage": "retain", "chunk": chunk_idx + 1})
                logger.error(
                    "[chunk {}/{}] FAILED {} units ({:.1f}s): {}: {}",
                    chunk_idx + 1,
                    chunk_count,
                    len(chunk),
                    elapsed,
                    type(exc).__name__,
                    exc,
                )
            processed_so_far = (chunk_idx + 1) * args.chunk_size
            logger.info("{}", prog.aggregate_line(min(processed_so_far, len(rendered))))

    set_measurement("units_retained", prog.retained, "none")
    set_measurement("units_failed", prog.failed, "none")
    set_measurement("units_skipped_empty", prog.skipped, "none")
    transaction.__exit__(None, None, None)

    logger.info(
        "\nretained={} skipped(empty)={} failed={} into bank {!r}",
        prog.retained,
        prog.skipped,
        prog.failed,
        BANK,
    )


if __name__ == "__main__":
    main()
