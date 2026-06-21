"""Shared persistence helper for adapters.

Every adapter (iMessage, Spotify, and future sources) emits canonical
:class:`~core.schema.Event` rows and persists them through this single helper,
so they all land in **one unified ``events`` table** in **one SQLite database**
(``data/recall.db`` by default). The table is source-agnostic — each row carries
a ``source`` column ("imessage" / "spotify" / ...) — which is what makes a single
table the durable home for every source rather than one table per source.

Centralizing the write here (instead of each adapter calling
:class:`~storage.store.CapsuleStore` inline) keeps behavior identical across
adapters and gives one place to evolve when we later enrich the schema (e.g. an
event label, or a Hindsight-side reference back to the event id).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from core.schema import Event
from storage.store import DEFAULT_DB_PATH, CapsuleStore


def persist_events(
    events: Iterable[Event],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Upsert canonical events into the unified ``events`` table.

    Idempotent on event ``id`` (``CapsuleStore.add_events`` uses
    ``INSERT OR REPLACE``), so re-running an adapter over the same source is safe
    and will not create duplicates.

    Args:
        events: Canonical events emitted by an adapter's ``to_event``.
        db_path: SQLite file to write to. Defaults to the shared
            :data:`~storage.store.DEFAULT_DB_PATH`; pass ``":memory:"`` in tests.

    Returns:
        The number of events written.
    """
    return CapsuleStore(db_path).add_events(events)
