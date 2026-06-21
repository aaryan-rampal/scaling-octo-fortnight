"""Build the unified ``events`` table from all four sources, from scratch.

Reads the four local sources, projects each to canonical ``Event`` rows, and
persists them through the single ``persist_events`` write path so they land in
one SQLite file (``data/recall.db``).

**One trailing window per source bounds ingest** (``--days`` default, per-source
overrides). Only events inside a source's window are persisted, so the durable
store holds the slice the pipeline actually uses — not the whole library. The
expensive LLM enrichments (photo vision, Spotify artist vibes) then apply to
exactly what was ingested. iMessage contact names are resolved at ingest (no
LLM, just a Contacts-DB lookup).

LIVE on the slice pass: photo vision + artist vibes spend OpenRouter on cache
misses. Run the whole thing under Doppler.

Each source has ONE trailing ingest window that bounds what lands in
``recall.db`` — enrichment then applies to exactly what was ingested.
``--days`` sets the shared default; ``--imessage-days`` / ``--photos-days`` /
``--spotify-days`` / ``--claude-days`` override per source (0 = full history).

    env PYTHONPATH=src .venv/bin/python scripts/build_all_sources_db.py \\
        --days 30 --spotify-days 7
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from datetime import timedelta

from loguru import logger

from adapters import imessage
from adapters.llm_chats import ingest_export
from adapters.photos import enrich_photos, ingest_photos
from adapters.spotify import (
    DEFAULT_MIN_MS_PLAYED,
    enrich_records,
    read_records,
    records_to_events,
)
from core.logging import configure_logging
from core.schema import Event
from storage.persist import persist_events
from storage.store import DEFAULT_DB_PATH, CapsuleStore

IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
PHOTOS_DB = os.path.expanduser("~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite")
CLAUDE_EXPORT_DIR = "data/claude_export"  # holds conversations.json
SPOTIFY_EXPORT_DIR = "data/spotify_export"

IMESSAGE_TOP_N = 25


def _persist(name: str, events: list[Event]) -> int:
    """Persist one source's events and report the count."""
    written = persist_events(events)
    logger.info("{}: persisted {} events to the unified table", name, written)
    return written


def _run_phase(name: str, build: Callable[[], list[Event]]) -> int:
    """Build one source's events, persist them, and log start/end with timing.

    Args:
        name: Source name shown in the phase logs (e.g. ``"imessage"``).
        build: Zero-arg callable that returns the source's canonical events.

    Returns:
        The number of events persisted for the phase.
    """
    logger.info("{}: phase start", name)
    start = time.perf_counter()
    events = build()
    written = _persist(name, events)
    elapsed = time.perf_counter() - start
    logger.info("{}: phase complete: {} events in {:.1f}s", name, written, elapsed)
    return written


def _within_days(events: list[Event], days: int) -> list[Event]:
    """Keep only events within the trailing ``days`` of the latest one.

    The single per-source window: it bounds what lands in ``recall.db`` (ingest),
    so enrichment and retain downstream only ever see this slice. ``days <= 0``
    keeps everything (no cutoff).
    """
    if not events or days <= 0:
        return events
    cutoff = max(e.t_utc for e in events) - timedelta(days=days)
    return [e for e in events if e.t_utc >= cutoff]


def _photo_events(days: int) -> list[Event]:
    """Ingest the trailing-``days`` photos, vision-enriching exactly that slice."""
    records = ingest_photos(PHOTOS_DB)
    recent_ids = {e.id for e in _within_days([r.to_event() for r in records], days)}
    recent = [r for r in records if r.id in recent_ids]
    logger.info("photos: ingesting + vision-enriching {} (last {}d)", len(recent), days)
    return [r.to_event() for r in enrich_photos(recent)]


def _spotify_events(days: int) -> list[Event]:
    """Ingest the trailing-``days`` Spotify plays, vibe-enriching exactly that slice.

    Trivially-short plays are dropped via ``records_to_events`` (the adapter's
    ``min_ms_played`` noise filter), so the stored set matches a normal
    ``spotify.ingest`` rather than the raw streaming history.
    """
    records = [r for r in read_records(SPOTIFY_EXPORT_DIR) if r.ms_played >= DEFAULT_MIN_MS_PLAYED]
    recent_ids = {e.id for e in _within_days(records_to_events(records), days)}
    recent = [r for r in records if r.to_event().id in recent_ids]
    logger.info("spotify: ingesting + vibe-enriching {} (last {}d)", len(recent), days)
    enrich_records(recent)  # mutates records in place; vibes ride into to_event()
    return records_to_events(recent)


def main() -> None:
    """Ingest all four sources into the unified events table, slice-enriched."""
    ap = argparse.ArgumentParser(description="Build the unified events DB from all sources.")
    ap.add_argument(
        "--days",
        type=int,
        default=30,
        help="Default trailing ingest window (days) per source; any per-source flag overrides it. "
        "0 = no cutoff (full history).",
    )
    for src in ("imessage", "photos", "spotify", "claude"):
        ap.add_argument(
            f"--{src}-days",
            type=int,
            default=None,
            help=f"Trailing ingest window for {src} (defaults to --days).",
        )
    ap.add_argument(
        "--fresh", action="store_true", help="Delete the existing DB first (build from scratch)."
    )
    args = ap.parse_args()

    def _window(source: str) -> int:
        override = getattr(args, f"{source}_days")
        return override if override is not None else args.days

    configure_logging()

    if args.fresh and os.path.exists(DEFAULT_DB_PATH):
        os.remove(DEFAULT_DB_PATH)
        logger.info("Removed existing {} (--fresh)", DEFAULT_DB_PATH)

    logger.info(
        "Building {} (ingest windows: imessage={}d photos={}d spotify={}d claude={}d)",
        DEFAULT_DB_PATH,
        _window("imessage"),
        _window("photos"),
        _window("spotify"),
        _window("claude"),
    )

    _run_phase(
        "imessage",
        lambda: _within_days(
            imessage.ingest(IMESSAGE_TOP_N, db_path=IMESSAGE_DB), _window("imessage")
        ),
    )
    _run_phase("claude", lambda: _within_days(ingest_export(CLAUDE_EXPORT_DIR), _window("claude")))
    _run_phase("spotify", lambda: _spotify_events(_window("spotify")))
    _run_phase("photos", lambda: _photo_events(_window("photos")))

    store = CapsuleStore()
    try:
        total = len(store.list_events())
    finally:
        store.close()
    print(f"\nDone. Unified store at {DEFAULT_DB_PATH} ({total} events)")


if __name__ == "__main__":
    main()
