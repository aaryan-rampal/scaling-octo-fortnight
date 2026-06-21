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
from datetime import timedelta

from adapters import imessage
from adapters.llm_chats import ingest_export
from adapters.photos import enrich_photos, ingest_photos
from adapters.spotify import (
    DEFAULT_MIN_MS_PLAYED,
    enrich_records,
    read_records,
    records_to_events,
)
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
    print(f"  {name:9s}: {written:>6d} events")
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
    print(f"  photos   : enriching {len(recent)} of {len(records)} (last {days}d) with vision")
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
    print(f"  spotify  : enriching {len(recent)} of {len(records)} (last {days}d) with vibes")
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

    if args.fresh and os.path.exists(DEFAULT_DB_PATH):
        os.remove(DEFAULT_DB_PATH)
        print(f"Removed existing {DEFAULT_DB_PATH} (--fresh)")

    print(f"Building {DEFAULT_DB_PATH} from four sources:")

    _persist("imessage", imessage.ingest(IMESSAGE_TOP_N, db_path=IMESSAGE_DB))
    _persist("claude", ingest_export(CLAUDE_EXPORT_DIR))
    _persist("spotify", _spotify_events(args.enrich_days))
    photo_records = _enrich_photos_slice(ingest_photos(PHOTOS_DB), args.enrich_days)
    _persist("photos", [r.to_event() for r in photo_records])

    store = CapsuleStore()
    try:
        total = len(store.list_events())
    finally:
        store.close()
    print(f"\nDone. Unified store at {DEFAULT_DB_PATH} ({total} events)")


if __name__ == "__main__":
    main()
