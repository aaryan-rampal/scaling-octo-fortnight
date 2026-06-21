"""Temporal episode windowing.

Group a thread's events into episodes by splitting whenever the gap between
consecutive messages exceeds a threshold. Episode ids are deterministic so the
same events always produce the same episode boundaries and identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import timedelta
from itertools import pairwise

from recall.schema import Episode, Event, read_events_jsonl


def _episode_id(thread_id: str, first_event_id: str, t_start: str) -> str:
    """Compute a deterministic episode id.

    Args:
        thread_id: Thread the episode belongs to.
        first_event_id: ``id`` of the episode's first event.
        t_start: ISO timestamp of the first event.

    Returns:
        A stable 16-character hex digest derived from the inputs.
    """
    key = f"{thread_id}\x00{first_event_id}\x00{t_start}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _make_episode(thread_id: str, events: list[Event]) -> Episode:
    """Build an :class:`Episode` from a contiguous run of one thread's events.

    Args:
        thread_id: Thread the events belong to.
        events: Ordered, non-empty events that make up the episode.

    Returns:
        The constructed episode with a deterministic id and derived metadata.
    """
    first = events[0]
    last = events[-1]
    participants = sorted({e.author_role for e in events if e.author_role is not None})
    return Episode(
        id=_episode_id(thread_id, first.id, first.t_utc.isoformat()),
        thread_id=thread_id,
        t_start=first.t_utc,
        t_end=last.t_utc,
        participants=participants,
        events=list(events),
    )


def window_thread(events: list[Event], gap_minutes: int = 30) -> list[Episode]:
    """Split one thread's events into episodes on inter-message gaps.

    Events are sorted by timestamp. A new episode starts whenever the gap
    between consecutive messages strictly exceeds ``gap_minutes``; a gap of
    exactly ``gap_minutes`` keeps both messages in the same episode (the
    boundary is exclusive).

    Args:
        events: Events belonging to a single thread.
        gap_minutes: Maximum allowed gap, in minutes, within one episode.

    Returns:
        Episodes in chronological order; empty if ``events`` is empty.
    """
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e.t_utc)
    thread_id = ordered[0].thread_id
    if thread_id is None:
        raise ValueError(
            "window_thread requires conversational events with a thread_id; "
            f"event {ordered[0].id!r} (source {ordered[0].source!r}) has none"
        )
    gap = timedelta(minutes=gap_minutes)
    episodes: list[Episode] = []
    current: list[Event] = [ordered[0]]
    for prev, event in pairwise(ordered):
        if event.t_utc - prev.t_utc > gap:
            episodes.append(_make_episode(thread_id, current))
            current = [event]
        else:
            current.append(event)
    episodes.append(_make_episode(thread_id, current))
    return episodes


def build_episodes(events: list[Event], gap_minutes: int = 30) -> list[Episode]:
    """Window every thread present in ``events`` into episodes.

    Args:
        events: Events across any number of threads.
        gap_minutes: Maximum allowed gap, in minutes, within one episode.

    Returns:
        All episodes from all threads. Events are grouped by ``thread_id``
        before windowing so episodes never span threads. Non-conversational
        events (those with no ``thread_id``, e.g. photos) are skipped.
    """
    by_thread: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.thread_id is None:
            continue
        by_thread[event.thread_id].append(event)
    episodes: list[Episode] = []
    for thread_events in by_thread.values():
        episodes.extend(window_thread(thread_events, gap_minutes))
    return episodes


def _summary_lines(episodes: list[Episode]) -> list[str]:
    """Render a human-readable distribution summary for ``episodes``."""
    if not episodes:
        return ["episodes: 0"]
    sizes = [len(e.events) for e in episodes]
    singles = sum(1 for size in sizes if size == 1)
    return [
        f"episodes: {len(episodes)}",
        f"events: {sum(sizes)}",
        f"median size: {statistics.median(sizes):.1f}",
        f"mean size: {statistics.mean(sizes):.2f}",
        f"single-message episodes: {singles} ({singles / len(episodes):.1%})",
        f"largest episode: {max(sizes)} events",
    ]


def _write_episodes_jsonl(episodes: list[Episode], path: str) -> int:
    """Write episodes to JSONL, one serialized episode per line.

    Args:
        episodes: Episodes to serialize.
        path: Destination file path; overwritten if it exists.

    Returns:
        The number of episodes written.
    """
    with open(path, "w", encoding="utf-8") as fh:
        for episode in episodes:
            fh.write(json.dumps(episode.to_dict(), ensure_ascii=False))
            fh.write("\n")
    return len(episodes)


def main() -> None:
    """CLI entry point: read events, window them, write episodes."""
    parser = argparse.ArgumentParser(description="Window events into episodes.")
    parser.add_argument("--gap-minutes", type=int, default=30)
    parser.add_argument("--in", dest="in_path", default="data/events.jsonl")
    parser.add_argument("--out", dest="out_path", default="data/episodes.jsonl")
    args = parser.parse_args()

    events = read_events_jsonl(args.in_path)
    episodes = build_episodes(events, args.gap_minutes)
    _write_episodes_jsonl(episodes, args.out_path)

    print(f"read {len(events)} events from {args.in_path}")
    print(f"wrote {len(episodes)} episodes to {args.out_path}")
    for line in _summary_lines(episodes):
        print(f"  {line}")


if __name__ == "__main__":
    main()
