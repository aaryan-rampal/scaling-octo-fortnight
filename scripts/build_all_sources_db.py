"""One-off: drive all four adapters into one unified ``events`` table.

Reads the four local sources, projects each to canonical ``Event`` rows, and
persists every source through the single ``persist_events`` write path so they
all land in one SQLite file (``data/recall.db``). This is a throwaway build
script, not a wired pipeline feature — it exists to produce an inspectable
``.db`` containing all four sources for inspection.

Run:
    .venv/bin/python scripts/build_all_sources_db.py
"""

from __future__ import annotations

import os

from adapters import imessage, spotify
from adapters.llm_chats import ingest_export
from adapters.photos import ingest_photos
from core.schema import Event
from storage.persist import persist_events
from storage.store import DEFAULT_DB_PATH

IMESSAGE_DB = os.path.expanduser("~/Library/Messages/chat.db")
PHOTOS_DB = os.path.expanduser("~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite")
CLAUDE_EXPORT_DIR = "data/claude_export"  # holds conversations.json
SPOTIFY_EXPORT_DIR = "data/spotify_export"

IMESSAGE_TOP_N = 25


def _persist(name: str, events: list[Event]) -> None:
    """Persist one source's events and report the count."""
    written = persist_events(events)
    print(f"  {name:9s}: {written:>6d} events")


def main() -> None:
    """Ingest all four sources into the unified events table."""
    print(f"Building {DEFAULT_DB_PATH} from four sources:")

    _persist("imessage", imessage.ingest(IMESSAGE_TOP_N, db_path=IMESSAGE_DB))
    _persist("claude", ingest_export(CLAUDE_EXPORT_DIR))
    _persist("spotify", spotify.ingest(SPOTIFY_EXPORT_DIR))
    _persist("photos", [r.to_event() for r in ingest_photos(PHOTOS_DB)])

    print(f"\nDone. Unified store at {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
