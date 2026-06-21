"""Tests for the shared adapter persistence helper and the unified events table.

Verifies that events from *different* sources land in one table, that writes are
idempotent, and that the durable provenance (``content_sha``) holds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from adaptors._persist import persist_events
from models.imessage import IMessageRecord
from models.spotify import SpotifyStreamRecord
from recall.store import CapsuleStore

_TS = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def _imessage_event():
    return IMessageRecord(
        rowid=1,
        thread_id="+15551234567",
        t_utc=_TS,
        content="hey",
        is_from_me=False,
    ).to_event()


def _spotify_event():
    return SpotifyStreamRecord.model_validate(
        {
            "ts": "2024-01-01T12:05:00Z",
            "ms_played": 200000,
            "master_metadata_track_name": "Pasoori",
            "master_metadata_album_artist_name": "Shae Gill",
            "spotify_track_uri": "spotify:track:7lvDsmTRXFE3dK4OjvRiWB",
        }
    ).to_event()


def test_persist_writes_events(tmp_path) -> None:
    db = tmp_path / "recall.db"
    n = persist_events([_imessage_event()], db_path=db)
    assert n == 1
    assert len(CapsuleStore(db).list_events()) == 1


def test_unified_table_holds_multiple_sources(tmp_path) -> None:
    db = tmp_path / "recall.db"
    persist_events([_imessage_event(), _spotify_event()], db_path=db)
    store = CapsuleStore(db)
    # One table, filtered by the source column.
    assert len(store.list_events()) == 2
    assert len(store.list_events(source="imessage")) == 1
    assert len(store.list_events(source="spotify")) == 1


def test_persist_is_idempotent(tmp_path) -> None:
    db = tmp_path / "recall.db"
    event = _spotify_event()
    persist_events([event], db_path=db)
    persist_events([event], db_path=db)  # re-run same source
    store = CapsuleStore(db)
    assert len(store.list_events()) == 1  # no duplicate
    assert store.verify_event(event.id) is True  # provenance intact
