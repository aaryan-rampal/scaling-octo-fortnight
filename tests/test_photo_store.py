"""Tests for the photos table persistence layer (round-trip + idempotency)."""

from __future__ import annotations

from datetime import UTC, datetime

from models.photo import PhotoRecord
from recall.photo_store import PhotoStore


def _record(pk: int, **overrides: object) -> PhotoRecord:
    """Build a PhotoRecord with sensible defaults for store tests."""
    data: dict[str, object] = {
        "id": f"uuid-{pk}",
        "captured_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        "lat": 49.28,
        "lng": -123.12,
        "original_filename": f"orig_{pk}.heic",
        "original_path": f"originals/D{pk}/IMG_{pk}.heic",
        "width": 100,
        "height": 200,
        "is_favorite": False,
        "is_hidden": False,
        "is_trashed": False,
        "kind": "photo",
        "people": ["Alice", "Bob"],
        "raw_ref": f"photos.sqlite#{pk}",
    }
    data.update(overrides)
    return PhotoRecord(**data)  # type: ignore[arg-type]


def test_add_and_roundtrip() -> None:
    store = PhotoStore(":memory:")
    try:
        written = store.add_photos([_record(1), _record(2)])
        assert written == 2
        rows = {r.id: r for r in store.list_photos()}
        assert set(rows) == {"uuid-1", "uuid-2"}
        r1 = rows["uuid-1"]
        assert r1.captured_at == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert r1.lat == 49.28
        assert r1.original_path == "originals/D1/IMG_1.heic"
        assert r1.kind == "photo"
        assert sorted(r1.people) == ["Alice", "Bob"]
        assert r1.raw_ref == "photos.sqlite#1"
    finally:
        store.close()


def test_none_gps_roundtrips() -> None:
    store = PhotoStore(":memory:")
    try:
        store.add_photos([_record(3, lat=None, lng=None, people=[])])
        r = store.list_photos()[0]
        assert r.lat is None
        assert r.lng is None
        assert r.people == []
    finally:
        store.close()


def test_flags_roundtrip_as_bool() -> None:
    store = PhotoStore(":memory:")
    try:
        store.add_photos(
            [_record(4, is_favorite=True, is_hidden=True, is_trashed=True, kind="video")]
        )
        r = store.list_photos()[0]
        assert r.is_favorite is True
        assert r.is_hidden is True
        assert r.is_trashed is True
        assert r.kind == "video"
    finally:
        store.close()


def test_idempotent_reingest() -> None:
    store = PhotoStore(":memory:")
    try:
        store.add_photos([_record(1), _record(2)])
        # Re-ingesting the same ids must not duplicate rows.
        store.add_photos([_record(1), _record(2)])
        assert len(store.list_photos()) == 2
    finally:
        store.close()
