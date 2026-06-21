"""Rung ① — per-source, inactivity-gap segmentation (zero LLM, no network).

Raw canonical :class:`~core.schema.Event` rows are grouped into memory-ready
:class:`Unit` runs. Each unit is one coherent run handed to a single rung-②
``retain``/render call. Segmentation is what makes downstream extraction *mean*
something: a lone low-context row extracts to nothing; a coherent run extracts
well.

The strategy is per-source inactivity-gap sessionization, the v1 default from
``docs/raw-to-principles-research.md`` §1:

* conversational sources (``imessage``, ``claude``): group by ``thread_id``,
  order by ``t_utc``, cut when the gap between consecutive events is strictly
  greater than ``T`` (default 30 min). A gap of exactly ``T`` does NOT split.
* non-conversational sources (``spotify``, ``photos``): per-source activity runs
  on the ``t_utc`` gap (same ``T``), with no ``thread_id`` grouping.

Provenance rule (non-negotiable): every :class:`Unit` carries a NON-EMPTY
``derived_from`` list of the contained ``Event.id`` values in time order. An
empty list is rejected at construction time — an empty derivation is a snapped
provenance chain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.schema import Event
from storage.store import CapsuleStore

#: Default inactivity gap before a run is cut into a new unit.
DEFAULT_GAP = timedelta(minutes=30)

#: Length of the trailing slice read from the store.
DEFAULT_SLICE = timedelta(days=7)

#: Sources whose events are grouped by ``thread_id`` before gap-sessionizing.
CONVERSATIONAL_SOURCES = frozenset({"imessage", "claude"})


@dataclass(frozen=True, slots=True)
class Unit:
    """One coherent run of events handed to a single rung-② call.

    Attributes:
        unit_id: Stable hash of ``(source, thread_id, t_start, t_end)``.
        source: Originating system (e.g. ``"imessage"``, ``"spotify"``).
        derived_from: NON-EMPTY list of ``Event.id`` values, in time order.
        t_start: Timestamp of the first event in the run.
        t_end: Timestamp of the last event in the run.
    """

    unit_id: str
    source: str
    derived_from: list[str]
    t_start: datetime
    t_end: datetime

    def __post_init__(self) -> None:
        """Enforce the provenance rule: ``derived_from`` must be non-empty."""
        if not self.derived_from:
            raise ValueError(
                "Unit.derived_from must be a non-empty list of Event.id values; "
                f"an empty derivation snaps the provenance chain (source={self.source!r})."
            )


def _unit_id(source: str, thread_id: str | None, t_start: datetime, t_end: datetime) -> str:
    """Return a stable hash of ``(source, thread_id, t_start, t_end)``."""
    payload = "\x1f".join(
        [
            source,
            thread_id or "",
            t_start.isoformat(),
            t_end.isoformat(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_unit(source: str, thread_id: str | None, run: list[Event]) -> Unit:
    """Build a :class:`Unit` from a non-empty, time-ordered ``run`` of events."""
    t_start = run[0].t_utc
    t_end = run[-1].t_utc
    return Unit(
        unit_id=_unit_id(source, thread_id, t_start, t_end),
        source=source,
        derived_from=[e.id for e in run],
        t_start=t_start,
        t_end=t_end,
    )


def _sessionize(
    source: str, thread_id: str | None, events: list[Event], gap: timedelta
) -> list[Unit]:
    """Cut one ordered event stream into units on inactivity gaps.

    Args:
        source: The source label for the emitted units.
        thread_id: The thread these events belong to, or ``None``.
        events: Events for a single ``(source, thread_id)`` key. Sorted here.
        gap: Inactivity gap; a span strictly greater than ``gap`` splits a run.

    Returns:
        Units in time order. Empty if ``events`` is empty.
    """
    ordered = sorted(events, key=lambda e: e.t_utc)
    units: list[Unit] = []
    run: list[Event] = []
    for event in ordered:
        if run and event.t_utc - run[-1].t_utc > gap:
            units.append(_make_unit(source, thread_id, run))
            run = []
        run.append(event)
    if run:
        units.append(_make_unit(source, thread_id, run))
    return units


def _group_key(event: Event) -> tuple[str, str | None]:
    """Return the ``(source, thread_id)`` key an event sessionizes within.

    Non-conversational sources collapse to a single per-source key (``thread_id``
    is dropped); conversational sources keep their ``thread_id``.
    """
    if event.source in CONVERSATIONAL_SOURCES:
        return (event.source, event.thread_id)
    return (event.source, None)


def segment_events(events: list[Event], gap: timedelta = DEFAULT_GAP) -> list[Unit]:
    """Segment events into per-source inactivity-gap units.

    Conversational sources group by ``thread_id``; non-conversational sources
    group per-source. Within each group, a gap strictly greater than ``gap``
    starts a new unit.

    Args:
        events: Canonical events to segment (any sources, any order).
        gap: Inactivity gap before a run is cut. Defaults to 30 minutes.

    Returns:
        Units ordered by ``t_start``. Empty input yields an empty list.
    """
    groups: dict[tuple[str, str | None], list[Event]] = {}
    for event in events:
        groups.setdefault(_group_key(event), []).append(event)

    units: list[Unit] = []
    for (source, thread_id), group in groups.items():
        units.extend(_sessionize(source, thread_id, group, gap))
    units.sort(key=lambda u: u.t_start)
    return units


def _slice_recent(events: list[Event], window: timedelta) -> list[Event]:
    """Keep only events within ``window`` of the latest event's timestamp."""
    if not events:
        return []
    cutoff = max(e.t_utc for e in events) - window
    return [e for e in events if e.t_utc >= cutoff]


def segment_recent(
    db_path: str | None = None,
    gap: timedelta = DEFAULT_GAP,
    window: timedelta = DEFAULT_SLICE,
) -> list[Unit]:
    """Read the trailing slice of the store and segment it into units.

    Opens ``data/recall.db`` (read-only intent: only ``list_events`` is called),
    keeps events within ``window`` of the latest timestamp, and runs
    :func:`segment_events`.

    Args:
        db_path: Path to the SQLite store; defaults to ``CapsuleStore``'s default.
        gap: Inactivity gap before a run is cut. Defaults to 30 minutes.
        window: Trailing slice to keep. Defaults to 7 days.

    Returns:
        Units ordered by ``t_start`` for the recent slice.
    """
    store = CapsuleStore() if db_path is None else CapsuleStore(db_path)
    try:
        events = store.list_events()
    finally:
        store.close()
    return segment_events(_slice_recent(events, window), gap)
