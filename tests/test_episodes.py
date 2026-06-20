"""Tests for temporal episode windowing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from recall.episodes import build_episodes, window_thread
from recall.schema import Event

BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def _event(
    minutes: float,
    *,
    thread_id: str = "t1",
    author_role: str = "self",
    suffix: str = "",
) -> Event:
    """Construct a synthetic event offset ``minutes`` from ``BASE``."""
    offset = int(minutes * 60)
    return Event(
        id=f"{thread_id}-{offset}{suffix}",
        t_utc=BASE + timedelta(minutes=minutes),
        author_role=author_role,
        content="hi",
        thread_id=thread_id,
        reply_to=None,
        raw_ref=f"chat.db#{offset}{suffix}",
    )


def test_messages_within_gap_share_episode() -> None:
    """Two messages 10 minutes apart land in one episode."""
    episodes = window_thread([_event(0), _event(10)], gap_minutes=30)
    assert len(episodes) == 1
    assert len(episodes[0].events) == 2


def test_messages_beyond_gap_split() -> None:
    """Two messages 40 minutes apart split into two episodes."""
    episodes = window_thread([_event(0), _event(40)], gap_minutes=30)
    assert len(episodes) == 2
    assert all(len(ep.events) == 1 for ep in episodes)


def test_exact_boundary_is_inclusive() -> None:
    """A gap of exactly gap_minutes keeps messages together.

    The boundary is exclusive on the split condition (``> gap``), so an
    exactly-30-minute gap does NOT start a new episode.
    """
    episodes = window_thread([_event(0), _event(30)], gap_minutes=30)
    assert len(episodes) == 1
    assert len(episodes[0].events) == 2


def test_deterministic_ids() -> None:
    """Identical inputs produce identical episode ids."""
    events = [_event(0), _event(5), _event(40), _event(45)]
    first = window_thread(events, gap_minutes=30)
    second = window_thread(events, gap_minutes=30)
    assert [ep.id for ep in first] == [ep.id for ep in second]
    assert len({ep.id for ep in first}) == 2


def test_threads_never_merge() -> None:
    """Events from two threads never combine into one episode."""
    events = [
        _event(0, thread_id="a"),
        _event(1, thread_id="b"),
        _event(2, thread_id="a"),
        _event(3, thread_id="b"),
    ]
    episodes = build_episodes(events, gap_minutes=30)
    assert len(episodes) == 2
    for ep in episodes:
        thread_ids = {e.thread_id for e in ep.events}
        assert thread_ids == {ep.thread_id}


def test_participants_are_sorted_unique_roles() -> None:
    """Participants list the sorted unique author roles in the episode."""
    events = [
        _event(0, author_role="self", suffix="a"),
        _event(1, author_role="other", suffix="b"),
        _event(2, author_role="self", suffix="c"),
    ]
    episodes = window_thread(events, gap_minutes=30)
    assert len(episodes) == 1
    assert episodes[0].participants == ["other", "self"]


def test_empty_input() -> None:
    """Windowing no events yields no episodes."""
    assert window_thread([], gap_minutes=30) == []
    assert build_episodes([], gap_minutes=30) == []
