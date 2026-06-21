"""Dump the live Hindsight memory bank straight into recall.db.

Reads all memories from the ``slice-7d`` bank (paginated), reconstructs their
raw-event provenance by re-segmenting ``data/recall.db`` with the same 30-day
window the retain used, and writes the memory layer (``memories`` +
``memory_events``) directly into recall.db via
:class:`storage.principle_store.PrincipleStore` — **no JSON at rest**.

This is the dump stage of the DB-as-truth pipeline: it owns the memory layer,
runs before ``link`` (which owns the principle layer), and resets only its own
two tables in one transaction (the principle/edge tables and the raw
``events`` / ``capsules`` / ``media`` are untouched).

``--out`` still writes the legacy JSON snapshot for human inspection / EDA
(``scripts/eda_bank.py``), but it is **observability-only and not written by
default** — the DB is the source of truth.

READ-ONLY against Hindsight — no OpenRouter extraction calls are made. Boots
embedded Hindsight (needs OPENROUTER_API_KEY in env for embeddings config, but
only reads memory).

Run:
    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/dump_bank.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

from loguru import logger

from core.logging import configure_logging
from core.schema import Event
from pipeline.segment import Unit, segment_recent
from runtime.hindsight import embedded_hindsight
from storage.principle_store import DEFAULT_DB_PATH, PrincipleStore
from storage.store import CapsuleStore

BANK = "slice-7d"
WINDOW_DAYS = 30


def _paginate_memories(client, bank_id: str) -> list[dict]:
    """Fetch all memories from a bank, paginating until complete.

    Args:
        client: A connected Hindsight client.
        bank_id: The bank to read from.

    Returns:
        All memory dicts from the bank.
    """
    memories: list[dict] = []
    offset = 0
    limit = 200
    total: int | None = None

    while True:
        resp = client.list_memories(bank_id=bank_id, type=None, limit=limit, offset=offset)
        if total is None:
            total = int(resp.total)
            logger.info("bank={!r} total={}", bank_id, total)
        memories.extend(resp.items)
        offset += len(resp.items)
        logger.debug("paginated: fetched {} / {}", len(memories), total)
        if not resp.items or len(memories) >= total:  # type: ignore[operator]
            break

    logger.info("paginated: collected {} memories total", len(memories))
    return memories


def _build_unit_map(window_days: int) -> dict[str, Unit]:
    """Re-segment the store with the retain window and index by unit_id.

    The re-segmentation MUST match what ``retain_slice.py`` used, or the
    reconstructed ``unit_id``s won't match the bank's ``document_id``s and
    provenance breaks. ``retain_slice.py`` defaults to ``--days 0`` → whole DB
    (``window=None``); ``0`` here means the same. Any positive value re-applies a
    trailing sub-slice (only correct if the retain used that same narrower window).

    Args:
        window_days: Trailing slice window in days; ``0`` = whole DB (no cutoff).

    Returns:
        Mapping of unit_id → Unit.
    """
    window = timedelta(days=window_days) if window_days > 0 else None
    units = segment_recent(window=window)
    logger.info("re-segmented {} units (window={})", len(units), window or "whole-db")
    by_source = Counter(u.source for u in units)
    logger.info("units by source: {}", dict(by_source))
    return {u.unit_id: u for u in units}


def _build_event_map() -> dict[str, Event]:
    """Load all events from the store and index by event id.

    Returns:
        Mapping of event_id → Event.
    """
    store = CapsuleStore()
    try:
        events = store.list_events()
    finally:
        store.close()
    logger.info("loaded {} events from store", len(events))
    return {e.id: e for e in events}


def _project_event(event: Event) -> dict:
    """Project an Event to the 5-field raw_event shape.

    Args:
        event: The canonical event to project.

    Returns:
        Dict with exactly: id, source, t_utc, content, additional_data.
    """
    return {
        "id": event.id,
        "source": event.source,
        "t_utc": event.t_utc.isoformat(),
        "content": event.content,
        "additional_data": dict(event.additional_data),
    }


def _entities_to_string(entities_field) -> str:
    """Normalize the Hindsight entities field to a comma-joined string.

    Hindsight may return entities as a list of dicts, a list of strings,
    a plain string, or None. We normalize to a comma-joined string.

    Args:
        entities_field: Raw entities value from a list_memories item.

    Returns:
        Comma-joined string, empty string if no entities.
    """
    if not entities_field:
        return ""
    if isinstance(entities_field, str):
        return entities_field
    if isinstance(entities_field, list):
        parts: list[str] = []
        for item in entities_field:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("entity") or item.get("value") or ""
                if name:
                    parts.append(str(name))
        return ", ".join(parts)
    return str(entities_field)


def _derive_source_and_fact_type(tags: list) -> tuple[str, str]:
    """Derive source and fact_type from a memory's tags list.

    Tags look like ``["imessage", "network:world", "author:other"]``.
    Source is the bare source tag; fact_type is the part after ``network:``.

    Args:
        tags: The memory's tags list (may be None).

    Returns:
        Tuple of (source, fact_type). Falls back to empty strings if not found.
    """
    source = ""
    fact_type = ""
    known_sources = {"imessage", "spotify", "photos", "claude"}
    for tag in tags or []:
        if tag in known_sources:
            source = tag
        elif tag.startswith("network:"):
            fact_type = tag[len("network:") :]
    return source, fact_type


def _build_snapshot(
    memories: list[dict],
    unit_map: dict[str, Unit],
    event_map: dict[str, Event],
) -> list[dict]:
    """Build the 9-field snapshot records from raw memories + provenance maps.

    Args:
        memories: Raw dicts from list_memories pagination.
        unit_map: unit_id → Unit from re-segmentation.
        event_map: event_id → Event from the store.

    Returns:
        List of 9-field snapshot dicts, one per memory.
    """
    matched = 0
    unmatched = 0
    source_coverage: Counter = Counter()
    source_empty: Counter = Counter()

    records: list[dict] = []
    for mem in memories:
        tags = mem.get("tags") or []
        source, fact_type = _derive_source_and_fact_type(tags)
        entities = _entities_to_string(mem.get("entities"))
        document_id = mem.get("document_id") or ""

        raw_events: list[dict] = []
        unit = unit_map.get(document_id)
        if unit is not None:
            matched += 1
            raw_events = [
                _project_event(event_map[eid]) for eid in unit.derived_from if eid in event_map
            ]
            if raw_events:
                source_coverage[source] += 1
            else:
                source_empty[source] += 1
        else:
            unmatched += 1

        records.append(
            {
                "memory_id": mem.get("id", ""),
                "text": mem.get("text", ""),
                "document_id": document_id,
                "source": source,
                "tags": tags,
                "entities": entities,
                "occurred_start": mem.get("occurred_start"),
                "fact_type": fact_type,
                "raw_events": raw_events,
            }
        )

    total = len(memories)
    logger.info(
        "provenance: {}/{} memories matched a unit ({} unmatched)",
        matched,
        total,
        unmatched,
    )
    logger.info("per-source raw_events coverage (non-empty): {}", dict(source_coverage))
    if source_empty:
        logger.warning(
            "per-source with empty raw_events (unit matched but no events): {}", dict(source_empty)
        )

    _assert_provenance(records, source_coverage)
    return records


def _assert_provenance(records: list[dict], source_coverage: Counter) -> None:
    """Fail loudly if any source has ZERO non-empty raw_events across all its memories.

    A whole source at zero means the provenance chain is silently broken for
    that source — we'd be writing a snapshot that looks complete but isn't.

    Args:
        records: The built snapshot records.
        source_coverage: Per-source counts of memories with non-empty raw_events.
    """
    sources_present = {r["source"] for r in records if r["source"]}
    for src in sources_present:
        if source_coverage[src] == 0:
            total_for_src = sum(1 for r in records if r["source"] == src)
            logger.error(
                "PROVENANCE FAILURE: source={!r} has {} memories but 0 with non-empty "
                "raw_events — snapshot would be silently broken. Aborting.",
                src,
                total_for_src,
            )
            sys.exit(1)


def main() -> None:
    """Dump the live Hindsight bank to a 9-field JSON snapshot."""
    configure_logging()

    ap = argparse.ArgumentParser(description="Dump Hindsight bank's memory layer into recall.db.")
    ap.add_argument("--bank", default=BANK, help=f"Bank id to read (default: {BANK}).")
    ap.add_argument(
        "--days",
        type=int,
        default=WINDOW_DAYS,
        help=f"Re-segmentation window in days (must match retain --days, default: {WINDOW_DAYS}).",
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="recall.db path.")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON snapshot path for human inspection (observability-only, "
        "not the source of truth). Omit to leave no JSON at rest.",
    )
    args = ap.parse_args()

    unit_map = _build_unit_map(args.days)
    event_map = _build_event_map()

    with embedded_hindsight() as client:
        memories = _paginate_memories(client, args.bank)

    if not memories:
        logger.error("no memories found in bank={!r} — nothing to write", args.bank)
        sys.exit(1)

    records = _build_snapshot(memories, unit_map, event_map)

    store = PrincipleStore.open(args.db)
    try:
        store.write_memory_layer(records)
    finally:
        store.close()
    logger.info("wrote {} memory records into {}", len(records), args.db)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("also wrote JSON snapshot (observability-only) to {}", args.out)


if __name__ == "__main__":
    main()
