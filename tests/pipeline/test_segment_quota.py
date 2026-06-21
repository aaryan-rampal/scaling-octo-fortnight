"""Fixture-only tests for the temporal-spread quota sampler (no network, no LLM)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from core.schema import Event
from pipeline.segment import DEFAULT_PER_INTERVAL, segment_windowed_quota
from storage.store import CapsuleStore

#: Newest reference instant; all fixture events are placed days before this.
NOW = datetime(2026, 6, 21, 12, 0, 0, tzinfo=UTC)


def _event(
    eid: str,
    days_ago: float,
    *,
    source: str = "imessage",
    thread_id: str | None = "thread-a",
    minute: int = 0,
) -> Event:
    """Build a minimal event ``days_ago`` days before NOW (plus ``minute`` offset)."""
    return Event(
        id=eid,
        t_utc=NOW - timedelta(days=days_ago) + timedelta(minutes=minute),
        author_role="self",
        content="hi",
        thread_id=thread_id,
        reply_to=None,
        raw_ref=f"raw#{eid}",
        source=source,
    )


def _imessage_convo(prefix: str, days_ago: float, n_msgs: int, thread_id: str) -> list[Event]:
    """A single iMessage conversation of ``n_msgs`` back-to-back messages."""
    return [
        _event(f"{prefix}-{i}", days_ago, thread_id=thread_id, minute=i)
        for i in range(n_msgs)
    ]


def _seed(tmp_path, events: list[Event]) -> str:
    db = tmp_path / "recall.db"
    store = CapsuleStore(str(db))
    store.add_events(events)
    store.close()
    return str(db)


def test_imessage_gate_drops_thin_convos_keeps_others(tmp_path) -> None:
    events: list[Event] = []
    # Thin iMessage convo (3 msgs < gate of 20) -> dropped.
    events += _imessage_convo("thin", days_ago=2, n_msgs=3, thread_id="t-thin")
    # Fat iMessage convo (25 msgs >= 20) -> kept.
    events += _imessage_convo("fat", days_ago=2, n_msgs=25, thread_id="t-fat")
    # Non-conversational source -> ungated, kept even though tiny.
    events += [_event("s1", 2, source="spotify", thread_id=None, minute=0)]

    db = _seed(tmp_path, events)
    units = segment_windowed_quota(db, min_imessage_msgs=20, per_interval=50)

    sources = Counter(u.source for u in units)
    assert sources["spotify"] == 1
    kept_im = {
        next(iter(u.derived_from)).split("-")[0] for u in units if u.source == "imessage"
    }
    assert "fat" in kept_im
    assert "thin" not in kept_im


def test_weekly_quota_caps_each_bucket(tmp_path) -> None:
    # A newest event at day 0 anchors the bucket grid. Week 0 (days 0-6) gets 5
    # separate spotify runs; week 2 (days 14-20) gets 4. With K=2 each bucket is
    # capped, and the day-0 anchor keeps the grid origin fixed regardless of which
    # tied units survive (all are length-1, so largest-first falls back to order).
    events: list[Event] = []
    # Week 0: 5 spotify runs at days 0-4 (one per day -> separate units).
    for i in range(5):
        events.append(_event(f"w0-{i}", days_ago=i, source="spotify", thread_id=None))
    # Week 2: 4 spotify runs at days 14-17.
    for i in range(4):
        events.append(_event(f"w2-{i}", days_ago=14 + i, source="spotify", thread_id=None))

    db = _seed(tmp_path, events)
    units = segment_windowed_quota(db, per_interval=2)

    # Bucket against the fixed grid origin (newest event = day 0), not the
    # post-cap max, so dropping the newest units can't shift bucket labels.
    origin = NOW
    per_bucket = Counter(int((origin - u.t_end) / timedelta(days=7)) for u in units)
    assert all(count <= 2 for count in per_bucket.values())
    # Both weeks represented (reach), each capped at 2.
    assert per_bucket[0] == 2
    assert per_bucket[2] == 2


def test_older_units_are_retained_for_reach(tmp_path) -> None:
    events = [
        _event("recent", 1, source="spotify", thread_id=None),
        _event("mid", 30, source="spotify", thread_id=None),
        _event("old", 80, source="spotify", thread_id=None),
    ]
    db = _seed(tmp_path, events)
    units = segment_windowed_quota(db, span=timedelta(days=90), per_interval=5)
    kept = {eid for u in units for eid in u.derived_from}
    assert kept == {"recent", "mid", "old"}


def test_span_excludes_events_beyond_reach(tmp_path) -> None:
    events = [
        _event("in", 10, source="spotify", thread_id=None),
        _event("out", 200, source="spotify", thread_id=None),  # beyond 90d span
    ]
    db = _seed(tmp_path, events)
    units = segment_windowed_quota(db, span=timedelta(days=90), per_interval=5)
    kept = {eid for u in units for eid in u.derived_from}
    assert "in" in kept
    assert "out" not in kept


def test_every_returned_unit_has_nonempty_derived_from(tmp_path) -> None:
    events: list[Event] = []
    events += _imessage_convo("fat", days_ago=3, n_msgs=25, thread_id="t-fat")
    events += [_event(f"s{i}", days_ago=10 + i, source="spotify", thread_id=None) for i in range(3)]
    db = _seed(tmp_path, events)
    units = segment_windowed_quota(db, per_interval=5)
    assert units
    assert all(u.derived_from for u in units)


def test_largest_unit_kept_when_bucket_overflows(tmp_path) -> None:
    # One fat (25-msg) and one borderline (20-msg) iMessage convo in the same week.
    events: list[Event] = []
    events += _imessage_convo("big", days_ago=1, n_msgs=25, thread_id="t-big")
    events += _imessage_convo("small", days_ago=2, n_msgs=20, thread_id="t-small")
    db = _seed(tmp_path, events)
    units = segment_windowed_quota(db, per_interval=1, min_imessage_msgs=20)
    assert len(units) == 1
    assert units[0].derived_from[0].startswith("big")


def test_default_per_interval_constant() -> None:
    assert DEFAULT_PER_INTERVAL == 9
