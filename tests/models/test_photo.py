"""Tests that photos reach the unified events table via the canonical Event.

Photos are non-conversational, so their canonical Event leaves the conversational
fields (author_role / content / thread_id / reply_to) empty and carries the
photo-only metadata in ``additional_data``. This mirrors how iMessage and Spotify
flow through ``storage.persist.persist_events`` into the single events table.
"""

from __future__ import annotations

from datetime import UTC, datetime

from models.photo import PhotoRecord
from storage.persist import persist_events
from storage.store import CapsuleStore

_TS = datetime(2024, 5, 1, 9, 30, 0, tzinfo=UTC)


def _photo_record() -> PhotoRecord:
    return PhotoRecord(
        id="ABC-UUID",
        captured_at=_TS,
        lat=37.4,
        lng=-122.1,
        original_filename="IMG_0001.HEIC",
        original_path="originals/0/IMG_0001.HEIC",
        width=4032,
        height=3024,
        is_favorite=True,
        is_hidden=False,
        is_trashed=False,
        kind="photo",
        people=["Alice", "Bob"],
        raw_ref="photos.sqlite#1",
    )


def test_to_event_lands_on_canonical_event() -> None:
    event = _photo_record().to_event()
    assert event.source == "photos"
    assert event.id == "ABC-UUID"
    assert event.t_utc == _TS
    assert event.raw_ref == "photos.sqlite#1"
    # photos are non-conversational: the conversational fields stay empty.
    assert event.author_role is None
    assert event.content is None
    assert event.thread_id is None
    assert event.reply_to is None
    # the photo-only metadata rides along in additional_data.
    assert event.additional_data["lat"] == 37.4
    assert event.additional_data["lng"] == -122.1
    assert event.additional_data["width"] == 4032
    assert event.additional_data["height"] == 3024
    assert event.additional_data["is_favorite"] is True
    assert event.additional_data["kind"] == "photo"
    assert event.additional_data["people"] == ["Alice", "Bob"]
    assert event.additional_data["original_path"] == "originals/0/IMG_0001.HEIC"


def test_photos_persist_into_unified_events_table(tmp_path) -> None:
    db = tmp_path / "recall.db"
    n = persist_events([_photo_record().to_event()], db_path=db)
    assert n == 1
    store = CapsuleStore(db)
    assert len(store.list_events(source="photos")) == 1
    # round-trip keeps the additional_data intact.
    stored = store.list_events(source="photos")[0]
    assert stored.additional_data["people"] == ["Alice", "Bob"]


def test_photo_event_round_trips_through_dict() -> None:
    event = _photo_record().to_event()
    restored = type(event).from_dict(event.to_dict())
    assert restored == event
