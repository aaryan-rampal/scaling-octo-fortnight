"""Tests for the Capsule -> canonical Event projection (the honest write path).

A user-created capsule must land on the same provenance path as the passive
sources: persisted as a canonical Event (source="capsule") in the unified events
table, so it is a traceable raw_data row ready to rise into memory.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.capsule import CAPSULE_SOURCE, Capsule, Media

_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _capsule(**overrides) -> Capsule:
    base = dict(
        id="c1",
        created_at=_TS,
        place_name="Moffitt Library",
        lat=37.872,
        lng=-122.260,
        media=[
            Media(
                id="m1",
                capsule_id="c1",
                kind="photo",
                file_path="c1/photo.jpg",
                mime="image/jpeg",
                byte_size=123,
            )
        ],
    )
    base.update(overrides)
    return Capsule(**base)


def test_to_event_is_canonical_capsule_event() -> None:
    e = _capsule().to_event()
    assert e.source == CAPSULE_SOURCE
    assert e.author_role == "self"  # the user intentionally created it
    assert e.thread_id is None  # a standalone moment, not a conversation
    assert e.raw_ref == "capsule#c1"
    assert e.id == "c1"


def test_to_event_carries_place_and_media_in_additional_data() -> None:
    e = _capsule().to_event()
    assert e.additional_data["place_name"] == "Moffitt Library"
    assert e.additional_data["lat"] == 37.872
    assert e.additional_data["media"][0]["kind"] == "photo"
    assert e.additional_data["media"][0]["file_path"] == "c1/photo.jpg"


def test_to_event_note_becomes_content() -> None:
    assert _capsule().to_event().content is None  # no note by default
    assert _capsule().to_event(note="felt good here").content == "felt good here"


def test_to_event_pure_no_disk_io() -> None:
    # The projection must not read the media binaries; a bogus file_path is fine.
    e = _capsule(media=[]).to_event()
    assert e.additional_data["media"] == []
    assert e.content is None
