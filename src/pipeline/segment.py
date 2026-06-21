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

from loguru import logger

from core.schema import Event
from storage.store import CapsuleStore

#: Default inactivity gap before a run is cut into a new unit.
DEFAULT_GAP = timedelta(minutes=30)

#: Sources whose events are grouped by ``thread_id`` before gap-sessionizing.
CONVERSATIONAL_SOURCES = frozenset({"imessage", "claude"})

#: Default weekly quota (units kept per interval) for :func:`segment_windowed_quota`.
#: Picked so a 90-day span with ~13 weekly buckets totals ~120 units — matching a
#: contiguous 30-day run's volume (~119 units on the present ``recall.db``) while
#: spreading that budget across 90 days of reach instead of one recency block.
DEFAULT_PER_INTERVAL = 9


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
    window: timedelta | None = None,
) -> list[Unit]:
    """Read the store and segment it into units.

    Opens ``data/recall.db`` (read-only intent: only ``list_events`` is called)
    and runs :func:`segment_events`. By default segments the **whole** store —
    the ingest step already bounds what lands there, so retain consumes all of it.
    Pass ``window`` only to retain a narrower sub-slice than was ingested.

    Args:
        db_path: Path to the SQLite store; defaults to ``CapsuleStore``'s default.
        gap: Inactivity gap before a run is cut. Defaults to 30 minutes.
        window: Optional trailing slice to keep. ``None`` (default) segments
            every event in the store.

    Returns:
        Units ordered by ``t_start``.
    """
    store = CapsuleStore() if db_path is None else CapsuleStore(db_path)
    try:
        events = store.list_events()
    finally:
        store.close()
    if window is not None:
        events = _slice_recent(events, window)
    return segment_events(events, gap)


def _passes_imessage_gate(unit: Unit, min_imessage_msgs: int) -> bool:
    """Return True unless ``unit`` is a thin iMessage conversation.

    iMessage units with fewer than ``min_imessage_msgs`` source events are dropped
    as thin/spam conversations. Non-iMessage sources have no meaningful message
    count and always pass.
    """
    if unit.source != "imessage":
        return True
    return len(unit.derived_from) >= min_imessage_msgs


def _bucket_index(t_end: datetime, newest: datetime, interval: timedelta) -> int:
    """Return which ``interval`` bucket ``t_end`` falls in, counting back from newest."""
    return int((newest - t_end) / interval)


def _select_largest(units: list[Unit], per_interval: int) -> list[Unit]:
    """Keep the ``per_interval`` units with the most ``derived_from`` events.

    The per-bucket selection policy (swap this helper to change it — e.g. to an
    evenly-strided pick). Largest-first biases toward substantive runs.
    """
    ranked = sorted(units, key=lambda u: len(u.derived_from), reverse=True)
    return ranked[:per_interval]


def _apply_weekly_quota(
    units: list[Unit], interval: timedelta, per_interval: int
) -> list[Unit]:
    """Bucket units by interval (relative to newest ``t_end``) and cap each bucket.

    Within every bucket, :func:`_select_largest` keeps the top ``per_interval``
    units. The kept units are returned in time order (by ``t_start``).
    """
    if not units:
        return []
    newest = max(u.t_end for u in units)
    buckets: dict[int, list[Unit]] = {}
    for unit in units:
        idx = _bucket_index(unit.t_end, newest, interval)
        buckets.setdefault(idx, []).append(unit)

    kept: list[Unit] = []
    for bucket in buckets.values():
        kept.extend(_select_largest(bucket, per_interval))
    kept.sort(key=lambda u: u.t_start)
    return kept


def _stratify_by_source_budget(
    units: list[Unit], ceiling: int, floor: int
) -> list[Unit]:
    """Cap each source's contributed EVENTS at ``ceiling``, warning below ``floor``.

    The imbalance Hindsight sees is event-driven, not unit-driven: a dense source
    (e.g. claude conversations) folds in far more events per unit, so it dominates
    the synthesized memories. This keeps whole units per source — largest first —
    until that source's cumulative ``derived_from`` count would exceed ``ceiling``,
    so every source contributes at most ``ceiling`` events. Sources whose total
    available events fall below ``floor`` are kept entirely (thin sources are not
    inflated — honesty over forced equality) but logged so the skew is visible.

    Args:
        units: Units already quota-selected (whole units, provenance intact).
        ceiling: Max events any single source may contribute (0 = no cap).
        floor: Minimum events we'd like per source; a source under it is kept
            whole and a warning is logged (we cannot synthesize events we lack).

    Returns:
        The kept units, ordered by ``t_start``. Whole units only — never reshaped.
    """
    if ceiling <= 0:
        return units
    by_source: dict[str, list[Unit]] = {}
    for u in units:
        by_source.setdefault(u.source, []).append(u)

    kept: list[Unit] = []
    for source, group in by_source.items():
        ranked = sorted(group, key=lambda u: len(u.derived_from), reverse=True)
        total = sum(len(u.derived_from) for u in ranked)
        running = 0
        taken: list[Unit] = []
        for u in ranked:
            if running + len(u.derived_from) > ceiling and taken:
                break
            taken.append(u)
            running += len(u.derived_from)
        kept.extend(taken)
        logger.info(
            "stratify {}: {} events available -> {} kept ({} units, ceiling={})",
            source,
            total,
            running,
            len(taken),
            ceiling,
        )
        if total < floor:
            logger.warning(
                "stratify {}: only {} events available (< floor {}) — source "
                "under-represented; cannot synthesize what isn't ingested",
                source,
                total,
                floor,
            )
    kept.sort(key=lambda u: u.t_start)
    return kept


def segment_windowed_quota(
    db_path: str | None = None,
    gap: timedelta = DEFAULT_GAP,
    span: timedelta = timedelta(days=90),
    interval: timedelta = timedelta(days=7),
    per_interval: int = DEFAULT_PER_INTERVAL,
    min_imessage_msgs: int = 20,
    source_event_ceiling: int = 0,
    source_event_floor: int = 0,
) -> list[Unit]:
    """Segment a long span, then thin it to an even per-interval quota.

    Takes a wide ``span`` of reach at a bounded cost by slicing it into
    ``interval`` buckets and keeping only ``per_interval`` units per bucket. A
    quality gate drops thin iMessage conversations before the quota; other sources
    pass ungated. The provenance invariant is preserved — whole units are dropped,
    never reshaped, so every returned ``Unit`` keeps its non-empty ``derived_from``.

    Args:
        db_path: Path to the SQLite store; defaults to ``CapsuleStore``'s default.
        gap: Inactivity gap before a run is cut. Defaults to 30 minutes.
        span: Trailing reach to consider, from the latest event. Defaults to 90 days.
        interval: Bucket width for the quota. Defaults to 7 days (weekly).
        per_interval: Units kept per bucket (K). Defaults to
            :data:`DEFAULT_PER_INTERVAL`.
        min_imessage_msgs: Minimum source events for an iMessage unit to survive
            the gate. Defaults to 20.
        source_event_ceiling: Max events any single source may contribute, applied
            after the quota to stop a dense source (claude) dominating Hindsight's
            synthesized memories. ``0`` (default) disables stratification.
        source_event_floor: Minimum events we'd like per source; sources below it
            are kept whole and a warning is logged. Only used when ceiling > 0.

    Returns:
        Units ordered by ``t_start``: gated, quota-capped, then (optionally)
        stratified to an even per-source event budget.
    """
    store = CapsuleStore() if db_path is None else CapsuleStore(db_path)
    try:
        events = store.list_events()
    finally:
        store.close()
    events = _slice_recent(events, span)
    units = segment_events(events, gap)
    gated = [u for u in units if _passes_imessage_gate(u, min_imessage_msgs)]
    quota = _apply_weekly_quota(gated, interval, per_interval)
    return _stratify_by_source_budget(quota, source_event_ceiling, source_event_floor)
