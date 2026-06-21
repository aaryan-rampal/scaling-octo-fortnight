"""Build the unified ``events`` table from all four sources, from scratch.

Reads the four local sources, projects each to canonical ``Event`` rows, and
persists them through the single ``persist_events`` write path so they land in
one SQLite file (``data/recall.db``). The full library of every source is stored
(per the design: the durable store holds everything; downstream loaders filter).

**Enrichment policy (LLM cost lives here, in one place):** the durable store
holds the *whole* library, but the expensive LLM enrichments — photo vision and
Spotify artist vibes — are computed only for the **trailing slice** that the
retain step actually consumes. Older rows are stored unenriched; they cost
nothing because nothing downstream reads them yet. iMessage contact names are
resolved for the whole set (no LLM, just a Contacts-DB lookup), so they ride in
at ingest.

LIVE on the slice pass: photo vision + artist vibes spend OpenRouter on cache
misses. Run the whole thing under Doppler.

    env PYTHONPATH=src .venv/bin/python scripts/build_all_sources_db.py --enrich-days 7
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
from models.photo import PhotoRecord
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


def _recent_event_ids(events: list[Event], days: int) -> set[str]:
    """Return the ids of events within the trailing ``days`` of the latest one."""
    if not events:
        return set()
    cutoff = max(e.t_utc for e in events) - timedelta(days=days)
    return {e.id for e in events if e.t_utc >= cutoff}


def _enrich_photos_slice(records: list[PhotoRecord], days: int) -> list[PhotoRecord]:
    """Vision-enrich only the trailing-``days`` photo records (others pass through).

    ``enrich_photos`` is given just the slice, so only those photos are ever sent
    to the vision model; the rest of the library is returned unchanged.
    """
    recent_ids = _recent_event_ids([r.to_event() for r in records], days)
    recent = [r for r in records if r.id in recent_ids]
    rest = [r for r in records if r.id not in recent_ids]
    logger.info(
        "photos: enriching {} of {} (last {}d) with vision", len(recent), len(records), days
    )
    return enrich_photos(recent) + rest


def _spotify_events(days: int) -> list[Event]:
    """Read the full Spotify library, vibe-enriching only the trailing slice.

    Trivially-short plays are dropped via ``records_to_events`` (the adapter's
    ``min_ms_played`` noise filter), so the stored set matches a normal
    ``spotify.ingest`` rather than the raw streaming history.
    """
    records = [r for r in read_records(SPOTIFY_EXPORT_DIR) if r.ms_played >= DEFAULT_MIN_MS_PLAYED]
    recent_ids = _recent_event_ids(records_to_events(records), days)
    recent = [r for r in records if r.to_event().id in recent_ids]
    logger.info(
        "spotify: enriching {} of {} (last {}d) with vibes", len(recent), len(records), days
    )
    enrich_records(recent)  # mutates records in place; vibes ride into to_event()
    return records_to_events(records)


def main() -> None:
    """Ingest all four sources into the unified events table, slice-enriched."""
    ap = argparse.ArgumentParser(description="Build the unified events DB from all sources.")
    ap.add_argument("--enrich-days", type=int, default=30, help="Trailing window to enrich.")
    ap.add_argument(
        "--fresh", action="store_true", help="Delete the existing DB first (build from scratch)."
    )
    args = ap.parse_args()

    configure_logging()

    if args.fresh and os.path.exists(DEFAULT_DB_PATH):
        os.remove(DEFAULT_DB_PATH)
        logger.info("Removed existing {} (--fresh)", DEFAULT_DB_PATH)

    logger.info("Building {} from four sources", DEFAULT_DB_PATH)

    def _photo_events() -> list[Event]:
        records = _enrich_photos_slice(ingest_photos(PHOTOS_DB), args.enrich_days)
        return [r.to_event() for r in records]

    _run_phase("imessage", lambda: imessage.ingest(IMESSAGE_TOP_N, db_path=IMESSAGE_DB))
    _run_phase("claude", lambda: ingest_export(CLAUDE_EXPORT_DIR))
    _run_phase("spotify", lambda: _spotify_events(args.enrich_days))
    _run_phase("photos", _photo_events)

    store = CapsuleStore()
    try:
        total = len(store.list_events())
    finally:
        store.close()
    print(f"\nDone. Unified store at {DEFAULT_DB_PATH} ({total} events)")


if __name__ == "__main__":
    main()
