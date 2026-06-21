"""Tests for the SQLite capsule/event store (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.capsule import Capsule, Media
from core.schema import Event
from storage.store import CapsuleStore


def _capsule(cid: str = "cap1", *, with_media: bool = True) -> Capsule:
    media = (
        [
            Media(
                id="m1",
                capsule_id=cid,
                kind="photo",
                file_path=f"{cid}/m1.jpg",
                mime="image/jpeg",
                byte_size=123,
            )
        ]
        if with_media
        else []
    )
    return Capsule(
        id=cid,
        created_at=datetime(2026, 6, 20, 18, 0, tzinfo=UTC),
        place_name="Moffitt Library",
        lat=37.872,
        lng=-122.260,
        media=media,
    )


def test_add_and_get_capsule_roundtrips_media() -> None:
    store = CapsuleStore(":memory:")
    store.add_capsule(_capsule())

    got = store.get_capsule("cap1")
    assert got is not None
    assert got.place_name == "Moffitt Library"
    assert got.lat == 37.872
    assert len(got.media) == 1
    assert got.media[0].kind == "photo"
    assert got.media[0].file_path == "cap1/m1.jpg"


def test_get_missing_capsule_returns_none() -> None:
    store = CapsuleStore(":memory:")
    assert store.get_capsule("nope") is None


def test_list_capsules_newest_first() -> None:
    store = CapsuleStore(":memory:")
    older = Capsule(
        id="old",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        place_name="A",
    )
    newer = Capsule(
        id="new",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
        place_name="B",
    )
    store.add_capsule(older)
    store.add_capsule(newer)

    ids = [c.id for c in store.list_capsules()]
    assert ids == ["new", "old"]


def test_capsule_without_media() -> None:
    store = CapsuleStore(":memory:")
    store.add_capsule(_capsule("bare", with_media=False))
    got = store.get_capsule("bare")
    assert got is not None
    assert got.media == []


def test_events_persist_and_filter_by_source() -> None:
    store = CapsuleStore(":memory:")
    events = [
        Event(
            id="e1",
            t_utc=datetime(2026, 6, 20, tzinfo=UTC),
            author_role="self",
            content="hi",
            thread_id="t1",
            reply_to=None,
            raw_ref="chat.db#1",
            source="imessage",
        ),
        Event(
            id="e2",
            t_utc=datetime(2026, 6, 21, tzinfo=UTC),
            author_role="other",
            content="note text",
            thread_id="t2",
            reply_to=None,
            raw_ref="notes#1",
            source="notes",
        ),
    ]
    assert store.add_events(events) == 2

    assert len(store.list_events()) == 2
    imessage = store.list_events(source="imessage")
    assert [e.id for e in imessage] == ["e1"]


def test_add_events_is_idempotent_on_id() -> None:
    store = CapsuleStore(":memory:")
    e = Event(
        id="e1",
        t_utc=datetime(2026, 6, 20, tzinfo=UTC),
        author_role="self",
        content="v1",
        thread_id="t1",
        reply_to=None,
        raw_ref="chat.db#1",
        source="imessage",
    )
    store.add_events([e])
    store.add_events([Event.from_dict({**e.to_dict(), "content": "v2"})])

    rows = store.list_events()
    assert len(rows) == 1
    assert rows[0].content == "v2"


def test_verify_event_provenance() -> None:
    store = CapsuleStore(":memory:")
    e = Event(
        id="e1",
        t_utc=datetime(2026, 6, 20, tzinfo=UTC),
        author_role="self",
        content="the night before the midterm",
        thread_id="t1",
        reply_to=None,
        raw_ref="chat.db#48213",
        source="imessage",
    )
    store.add_events([e])

    # Untampered content verifies against its ingest-time hash.
    assert store.verify_event("e1") is True
    # Unknown id reports None, not a false negative.
    assert store.verify_event("missing") is None


def test_verify_event_detects_tampering() -> None:
    store = CapsuleStore(":memory:")
    e = Event(
        id="e1",
        t_utc=datetime(2026, 6, 20, tzinfo=UTC),
        author_role="self",
        content="original",
        thread_id="t1",
        reply_to=None,
        raw_ref="chat.db#1",
        source="imessage",
    )
    store.add_events([e])
    # Simulate out-of-band tampering: change content but leave the stored hash.
    with store._cursor() as cur:
        cur.execute("UPDATE events SET content = 'altered' WHERE id = 'e1'")

    assert store.verify_event("e1") is False
