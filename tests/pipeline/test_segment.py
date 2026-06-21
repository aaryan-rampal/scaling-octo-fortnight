"""Fixture-only tests for rung ① segmentation (no network, no LLM)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.schema import Event
from pipeline.segment import (
    DEFAULT_GAP,
    Unit,
    segment_events,
    segment_recent,
)

BASE = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


def _event(
    eid: str,
    minutes: float,
    *,
    source: str = "imessage",
    thread_id: str | None = "thread-a",
    content: str | None = "hi",
) -> Event:
    """Build a minimal event at ``BASE + minutes``."""
    return Event(
        id=eid,
        t_utc=BASE + timedelta(minutes=minutes),
        author_role="self",
        content=content,
        thread_id=thread_id,
        reply_to=None,
        raw_ref=f"raw#{eid}",
        source=source,
    )


def test_empty_input_yields_no_units() -> None:
    assert segment_events([]) == []


def test_single_thread_splits_on_gap_over_t() -> None:
    events = [
        _event("a", 0),
        _event("b", 10),
        _event("c", 10 + 31),  # 31-minute gap > 30-minute T
        _event("d", 10 + 31 + 5),
    ]
    units = segment_events(events)
    assert len(units) == 2
    assert units[0].derived_from == ["a", "b"]
    assert units[1].derived_from == ["c", "d"]
    assert units[0].t_start == events[0].t_utc
    assert units[0].t_end == events[1].t_utc


def test_exactly_t_gap_does_not_split() -> None:
    events = [
        _event("a", 0),
        _event("b", 30),  # gap of exactly T=30 min: stays together
    ]
    units = segment_events(events)
    assert len(units) == 1
    assert units[0].derived_from == ["a", "b"]


def test_non_conversational_run_ignores_thread_id() -> None:
    events = [
        _event("p1", 0, source="spotify", thread_id=None, content=None),
        _event("p2", 5, source="spotify", thread_id=None, content=None),
        _event("p3", 5 + 40, source="spotify", thread_id=None, content=None),
    ]
    units = segment_events(events)
    assert [u.source for u in units] == ["spotify", "spotify"]
    assert units[0].derived_from == ["p1", "p2"]
    assert units[1].derived_from == ["p3"]


def test_separate_threads_are_segmented_independently() -> None:
    events = [
        _event("a", 0, thread_id="t1"),
        _event("b", 5, thread_id="t2"),
        _event("c", 6, thread_id="t1"),
    ]
    units = segment_events(events)
    by_thread = {tuple(u.derived_from) for u in units}
    assert ("a", "c") in by_thread
    assert ("b",) in by_thread


def test_units_sorted_by_t_start() -> None:
    events = [
        _event("late", 100, source="spotify", thread_id=None),
        _event("early", 0, thread_id="t1"),
    ]
    units = segment_events(events)
    assert units[0].t_start < units[1].t_start


def test_unit_id_stable_and_distinct() -> None:
    events = [_event("a", 0), _event("b", 40)]
    first = segment_events(events)
    second = segment_events(events)
    assert [u.unit_id for u in first] == [u.unit_id for u in second]
    assert first[0].unit_id != first[1].unit_id


def test_default_gap_is_thirty_minutes() -> None:
    assert timedelta(minutes=30) == DEFAULT_GAP


def test_empty_derived_from_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Unit(
            unit_id="x",
            source="imessage",
            derived_from=[],
            t_start=BASE,
            t_end=BASE,
        )


def _seed_store(tmp_path):
    from storage.store import CapsuleStore

    db = tmp_path / "recall.db"
    store = CapsuleStore(str(db))
    store.add_events(
        [
            _event("old", -60 * 24 * 30),  # 30 days before BASE
            _event("recent1", 0),
            _event("recent2", 10),
        ]
    )
    store.close()
    return str(db)


def test_segment_recent_default_reads_whole_store(tmp_path) -> None:
    # Default (no window): ingest already bounds the DB, so retain takes all of it.
    units = segment_recent(_seed_store(tmp_path))
    ids = [eid for u in units for eid in u.derived_from]
    assert "old" in ids
    assert set(ids) == {"old", "recent1", "recent2"}


def test_segment_recent_window_keeps_trailing_slice(tmp_path) -> None:
    # An explicit window retains only a narrower sub-slice than was ingested.
    units = segment_recent(_seed_store(tmp_path), window=timedelta(days=7))
    ids = [eid for u in units for eid in u.derived_from]
    assert "old" not in ids
    assert ids == ["recent1", "recent2"]
