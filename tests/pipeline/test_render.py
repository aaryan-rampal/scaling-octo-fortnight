"""Fixture-only tests for rung-② rendering and the retain wrapper.

No network and no real Hindsight: the retain path is exercised with a fake
client. ``Unit`` is stubbed locally to the v0 contract shape so these tests do
not couple to rung ①'s module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from core.schema import Event
from pipeline.render import (
    MemoryRef,
    build_batch_item,
    render_unit,
    retain_batch_units,
    retain_unit,
)


@dataclass(frozen=True, slots=True)
class _Unit:
    """Local stand-in for the rung-① ``Unit`` contract shape."""

    unit_id: str
    source: str
    derived_from: list[str]
    t_start: datetime
    t_end: datetime


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 14, hour, minute, tzinfo=UTC)


def _event(**kwargs: Any) -> Event:
    base: dict[str, Any] = {
        "id": "e0",
        "t_utc": _ts(12),
        "author_role": None,
        "content": None,
        "thread_id": None,
        "reply_to": None,
        "raw_ref": "ref#0",
        "source": "imessage",
        "additional_data": {},
    }
    base.update(kwargs)
    return Event(**base)


def _unit(source: str, ids: list[str]) -> _Unit:
    return _Unit(
        unit_id=f"u-{source}",
        source=source,
        derived_from=ids,
        t_start=_ts(12),
        t_end=_ts(13),
    )


@dataclass
class _FakeClient:
    """Records the kwargs of the last retain call instead of hitting a server."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def retain(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


# --- render_unit: conversational -------------------------------------------------


def test_render_imessage_transcript_role_prefixed_in_order() -> None:
    events = [
        _event(id="a", author_role="self", content="hey", source="imessage", t_utc=_ts(12, 0)),
        _event(id="b", author_role="other", content="hi", source="imessage", t_utc=_ts(12, 1)),
    ]
    text = render_unit(_unit("imessage", ["a", "b"]), events)
    assert text == "self: hey\nother: hi"


def test_render_conversational_handles_missing_role_and_content() -> None:
    events = [_event(id="a", author_role=None, content=None, source="claude")]
    assert render_unit(_unit("claude", ["a"]), events) == "unknown: "


# --- render_unit: spotify --------------------------------------------------------


def test_render_spotify_templated_fact_per_play() -> None:
    events = [
        _event(
            id="s1",
            author_role="self",
            content="Listened to 'ROCKSTAR' by DaBaby (album BLAME IT ON BABY)",
            source="spotify",
            t_utc=_ts(9, 30),
        ),
    ]
    text = render_unit(_unit("spotify", ["s1"]), events)
    assert text == (
        "On 2026-06-14T09:30:00+00:00, listened to 'ROCKSTAR' by DaBaby (album BLAME IT ON BABY)"
    )


# --- render_unit: photos ---------------------------------------------------------


def test_render_photo_with_people() -> None:
    events = [
        _event(
            id="p1",
            source="photos",
            t_utc=_ts(15, 5),
            additional_data={"lat": 49.26, "lng": -123.25, "people": ["Alex", "Sam"]},
        ),
    ]
    text = render_unit(_unit("photos", ["p1"]), events)
    assert text == "On 2026-06-14T15:05:00+00:00, took a photo at 49.26, -123.25 with Alex, Sam"


def test_render_photo_without_people_or_geo() -> None:
    events = [
        _event(id="p2", source="photos", t_utc=_ts(16, 0), additional_data={"people": []}),
    ]
    text = render_unit(_unit("photos", ["p2"]), events)
    assert text == "On 2026-06-14T16:00:00+00:00, took a photo at an unknown location"


def test_render_empty_events_raises() -> None:
    with pytest.raises(ValueError, match="at least one event"):
        render_unit(_unit("imessage", ["a"]), [])


# --- render_unit: enrichment keys (allowlist) ------------------------------------


def test_render_imessage_uses_contact_name_for_other() -> None:
    events = [
        _event(
            id="a",
            author_role="other",
            content="hey",
            source="imessage",
            additional_data={"contact_name": "Marleigh"},
        ),
    ]
    text = render_unit(_unit("imessage", ["a"]), events)
    assert text == "Marleigh: hey"


def test_render_imessage_contact_name_never_relabels_self() -> None:
    # A resolved name on a self-authored row must not overwrite the "self" role.
    events = [
        _event(
            id="a",
            author_role="self",
            content="hi",
            source="imessage",
            additional_data={"contact_name": "Marleigh"},
        ),
    ]
    assert render_unit(_unit("imessage", ["a"]), events) == "self: hi"


def test_render_photo_prefers_vision_description_over_geo() -> None:
    events = [
        _event(
            id="p1",
            source="photos",
            t_utc=_ts(15, 5),
            additional_data={
                "lat": 49.26,
                "lng": -123.25,
                "people": ["Alex"],
                "vision_description": "a golden sunset over the sea",
            },
        ),
    ]
    text = render_unit(_unit("photos", ["p1"]), events)
    assert text == "On 2026-06-14T15:05:00+00:00, a golden sunset over the sea with Alex"


def test_render_photo_falls_back_to_geo_without_vision() -> None:
    events = [
        _event(
            id="p2",
            source="photos",
            t_utc=_ts(16, 0),
            additional_data={"lat": 1.0, "lng": 2.0, "people": []},
        ),
    ]
    text = render_unit(_unit("photos", ["p2"]), events)
    assert text == "On 2026-06-14T16:00:00+00:00, took a photo at 1.0, 2.0"


def test_render_spotify_appends_vibe_when_absent_from_content() -> None:
    events = [
        _event(
            id="s1",
            author_role="self",
            content="Listened to 'Title' by Calvin Harris",
            source="spotify",
            t_utc=_ts(9, 30),
            additional_data={"artist_vibe": "high-energy EDM dance-pop"},
        ),
    ]
    text = render_unit(_unit("spotify", ["s1"]), events)
    assert text == (
        "On 2026-06-14T09:30:00+00:00, listened to 'Title' by Calvin Harris "
        "(high-energy EDM dance-pop)"
    )


def test_render_spotify_does_not_duplicate_vibe_already_in_content() -> None:
    events = [
        _event(
            id="s2",
            author_role="self",
            content="Listened to 'Title' by Calvin Harris (high-energy EDM dance-pop)",
            source="spotify",
            t_utc=_ts(9, 30),
            additional_data={"artist_vibe": "high-energy EDM dance-pop"},
        ),
    ]
    text = render_unit(_unit("spotify", ["s2"]), events)
    assert text.count("high-energy EDM dance-pop") == 1


def test_render_ignores_non_allowlisted_plumbing_keys() -> None:
    # Storage plumbing (paths, dimensions, flags) must never leak into the text.
    events = [
        _event(
            id="p3",
            source="photos",
            t_utc=_ts(16, 0),
            additional_data={
                "vision_description": "a quiet room",
                "original_path": "/Users/me/IMG_1.HEIC",
                "height": 4032,
                "is_favorite": True,
            },
        ),
    ]
    text = render_unit(_unit("photos", ["p3"]), events)
    assert text == "On 2026-06-14T16:00:00+00:00, a quiet room"
    assert "IMG_1" not in text and "4032" not in text


# --- retain_unit -----------------------------------------------------------------


def test_retain_unit_sets_document_id_to_unit_id() -> None:
    client = _FakeClient()
    unit = _unit("imessage", ["a", "b"])
    ref = retain_unit(client, unit, "self: hey", author_role="self")
    assert isinstance(ref, MemoryRef)
    # The durable provenance link: document_id == unit_id, carried on every memory.
    assert ref.document_id == "u-imessage"
    assert client.calls[0]["document_id"] == "u-imessage"
    assert ref.derived_from == ["u-imessage"]


def test_retain_unit_routes_self_to_experience_via_tags() -> None:
    client = _FakeClient()
    retain_unit(client, _unit("imessage", ["a"]), "self: hi", author_role="self")
    assert "network:experience" in client.calls[0]["tags"]


def test_retain_unit_routes_other_to_world_via_tags() -> None:
    client = _FakeClient()
    retain_unit(client, _unit("imessage", ["a"]), "other: hi", author_role="other")
    assert "network:world" in client.calls[0]["tags"]


def test_retain_unit_none_role_defaults_to_world() -> None:
    client = _FakeClient()
    retain_unit(client, _unit("photos", ["p1"]), "On ..., took a photo", author_role=None)
    tags = client.calls[0]["tags"]
    assert "network:world" in tags
    assert "author:unknown" in tags


def test_retain_unit_blank_text_raises() -> None:
    with pytest.raises(ValueError, match="non-empty rendered text"):
        retain_unit(_FakeClient(), _unit("imessage", ["a"]), "   ", author_role="self")


def test_memory_ref_rejects_empty_derived_from() -> None:
    with pytest.raises(ValueError, match="non-empty list"):
        MemoryRef(document_id="u", derived_from=[])


# --- build_batch_item: provenance + tags -----------------------------------------


def test_build_batch_item_document_id_equals_unit_id() -> None:
    unit = _unit("imessage", ["a", "b"])
    item = build_batch_item(unit, "self: hey", author_role="self")
    # Per-item document_id MUST equal unit_id — this is the provenance invariant.
    assert item["document_id"] == "u-imessage"


def test_build_batch_item_self_routes_to_experience() -> None:
    item = build_batch_item(_unit("imessage", ["a"]), "self: hi", author_role="self")
    assert "network:experience" in item["tags"]
    assert "author:self" in item["tags"]


def test_build_batch_item_other_routes_to_world() -> None:
    item = build_batch_item(_unit("imessage", ["a"]), "other: hi", author_role="other")
    assert "network:world" in item["tags"]
    assert "author:other" in item["tags"]


def test_build_batch_item_none_role_defaults_to_world() -> None:
    item = build_batch_item(_unit("photos", ["p1"]), "On ..., a photo", author_role=None)
    assert "network:world" in item["tags"]
    assert "author:unknown" in item["tags"]


def test_build_batch_item_includes_source_tag() -> None:
    item = build_batch_item(_unit("spotify", ["s1"]), "On ..., listened", author_role="self")
    assert "spotify" in item["tags"]


def test_build_batch_item_includes_timestamp() -> None:
    unit = _unit("imessage", ["a"])
    item = build_batch_item(unit, "self: hi", author_role="self")
    assert item["timestamp"] == unit.t_start.isoformat()


def test_build_batch_item_blank_text_raises() -> None:
    with pytest.raises(ValueError, match="non-empty rendered text"):
        build_batch_item(_unit("imessage", ["a"]), "   ", author_role="self")


def test_build_batch_item_content_matches_text() -> None:
    item = build_batch_item(_unit("imessage", ["a"]), "self: hello", author_role="self")
    assert item["content"] == "self: hello"


# --- retain_batch_units: batch client call ----------------------------------------


@dataclass
class _FakeBatchClient:
    """Records retain_batch calls instead of hitting a server."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def retain_batch(
        self,
        bank_id: str,
        items: list[dict[str, Any]],
        document_id: str | None = None,
        document_tags: list[str] | None = None,
        retain_async: bool = False,
    ) -> None:
        _ = document_id, document_tags, retain_async  # unused in stub
        self.calls.append({"bank_id": bank_id, "items": list(items)})


def test_retain_batch_units_passes_all_items() -> None:
    client = _FakeBatchClient()
    unit_a = _unit("imessage", ["a"])
    unit_b = _unit("spotify", ["s1"])
    items = [
        build_batch_item(unit_a, "self: hey", author_role="self"),
        build_batch_item(unit_b, "On ..., listened", author_role="self"),
    ]
    retain_batch_units(client, items, bank_id="test-bank")
    assert len(client.calls) == 1
    assert client.calls[0]["bank_id"] == "test-bank"
    assert len(client.calls[0]["items"]) == 2


def test_retain_batch_units_per_item_document_ids_are_distinct() -> None:
    """Each item in the batch has its own document_id — no collapsing."""
    client = _FakeBatchClient()
    unit_a = _unit("imessage", ["a"])
    # Manually construct a second unit with a different unit_id.
    unit_b = _Unit(
        unit_id="u-photos",
        source="photos",
        derived_from=["p1"],
        t_start=_ts(14),
        t_end=_ts(15),
    )
    items = [
        build_batch_item(unit_a, "self: hey", author_role="self"),
        build_batch_item(unit_b, "On ..., a photo", author_role=None),
    ]
    retain_batch_units(client, items)
    sent = client.calls[0]["items"]
    doc_ids = {i["document_id"] for i in sent}
    assert doc_ids == {"u-imessage", "u-photos"}, "each unit must carry its own document_id"


def test_retain_batch_units_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one item"):
        retain_batch_units(_FakeBatchClient(), [])
