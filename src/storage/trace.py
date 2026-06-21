"""Read path — trace a principle back through its provenance chain.

Given a principle id, walk the materialised provenance graph in SQLite
(``data/recall.db`` / ``data/derek_handoff/derek_sample.db``) down the fixed
ladder::

    principle ──principle_memories──▶ memories ──memory_events──▶ events

returning the principle plus every backing memory and, under each memory, the
raw events it was extracted from. This is the deterministic half of the
"why does this principle exist" feature: it only *surfaces* the provenance path
that already exists (CLAUDE.md §2) and writes nothing.

Schema reference: ``data/derek_handoff/SCHEMA.md`` is the contract for table and
column names. Every function takes an already-open :class:`sqlite3.Connection`,
so the caller owns the connection lifecycle — a test passes a fixture DB, the
CLI passes a real file, an HTTP handler reuses one connection per request.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TracedEvent:
    """One raw ground-truth row a memory was extracted from (the bottom rung).

    Attributes:
        id: The ``events.id`` of the raw message/item.
        t_utc: ISO-8601 UTC timestamp of the event.
        author_role: ``self`` (the user) / ``other`` / etc.
        content: The message or item text.
        raw_ref: Pointer into the original source (e.g. ``claude:<conv>#<msg>``).
        source: Originating source (``imessage`` / ``claude`` / ...).
    """

    id: str
    t_utc: str
    author_role: str
    content: str
    raw_ref: str
    source: str


@dataclass(frozen=True, slots=True)
class TracedMemory:
    """A synthesised memory backing a principle, with its raw events nested.

    Attributes:
        memory_id: The ``memories.memory_id`` (UUID).
        text: The abstracted memory text.
        source: Originating source of the memory.
        occurred_start: ISO timestamp the memory is anchored to (may be ``None``).
        events: The raw events this memory was extracted from (possibly empty).
    """

    memory_id: str
    text: str
    source: str
    occurred_start: str | None
    events: list[TracedEvent]


@dataclass(frozen=True, slots=True)
class PrincipleTrace:
    """A principle plus its full downward provenance closure.

    Attributes:
        principle_id: The ``principles.id``.
        text: The one-line principle surfaced to the user.
        confidence: ``0..1`` ledger-derived confidence.
        memories: The backing memories, each carrying its own raw events.
    """

    principle_id: str
    text: str
    confidence: float
    memories: list[TracedMemory]


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open a **read-only** connection with rows accessible by column name.

    Read-only (``mode=ro`` URI) for two reasons: this is a pure surfacing path
    that must never mutate the graph (CLAUDE.md §2), and it makes a missing file
    raise instead of silently creating an empty DB — so a wrong ``--db`` fails
    loudly rather than reporting "no principles".

    Args:
        path: Path to an existing SQLite provenance DB.

    Returns:
        A read-only connection whose ``row_factory`` yields :class:`sqlite3.Row`.

    Raises:
        sqlite3.OperationalError: If the file does not exist or cannot be opened.
    """
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


_PRINCIPLE_SQL = "SELECT id, text, confidence FROM principles WHERE id = ?"

#: The full trace ladder for one principle, flattened to (memory, event) rows.
#: LEFT JOINs keep a memory in the result even when it links no events, so a
#: thin-provenance principle still traces (with empty event lists) rather than
#: vanishing.
_LADDER_SQL = """
SELECT m.memory_id      AS memory_id,
       m.text           AS memory_text,
       m.source         AS memory_source,
       m.occurred_start AS occurred_start,
       e.id             AS event_id,
       e.t_utc          AS t_utc,
       e.author_role    AS author_role,
       e.content        AS content,
       e.raw_ref        AS raw_ref,
       e.source         AS event_source
FROM principle_memories pm
JOIN memories m            ON m.memory_id  = pm.memory_id
LEFT JOIN memory_events me ON me.memory_id = m.memory_id
LEFT JOIN events e         ON e.id         = me.event_id
WHERE pm.principle_id = ?
ORDER BY m.occurred_start, e.t_utc
"""


def _group_rows(rows: list[sqlite3.Row]) -> list[TracedMemory]:
    """Collapse flat (memory, event) rows into memories with nested events.

    Memory order is first-appearance order from the query (already sorted by
    ``occurred_start`` then ``t_utc``). Rows whose ``event_id`` is ``NULL`` come
    from the LEFT JOIN for a memory with no linked events — the memory is kept,
    the empty event row is skipped.

    Args:
        rows: The flat result of :data:`_LADDER_SQL`.

    Returns:
        One :class:`TracedMemory` per distinct memory, events nested.
    """
    by_mem: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        mid = r["memory_id"]
        if mid not in by_mem:
            by_mem[mid] = {
                "text": r["memory_text"],
                "source": r["memory_source"],
                "occurred_start": r["occurred_start"],
                "events": [],
                "seen_events": set(),
            }
            order.append(mid)
        eid = r["event_id"]
        # Dedupe within a memory: duplicate principle_memories / memory_events
        # rows multiply through the JOIN, so guard against re-adding the same id.
        if eid is not None and eid not in by_mem[mid]["seen_events"]:
            by_mem[mid]["seen_events"].add(eid)
            by_mem[mid]["events"].append(
                TracedEvent(
                    id=eid,
                    t_utc=r["t_utc"],
                    author_role=r["author_role"],
                    content=r["content"],
                    raw_ref=r["raw_ref"],
                    source=r["event_source"],
                )
            )
    return [
        TracedMemory(
            memory_id=mid,
            text=by_mem[mid]["text"],
            source=by_mem[mid]["source"],
            occurred_start=by_mem[mid]["occurred_start"],
            events=by_mem[mid]["events"],
        )
        for mid in order
    ]


def trace_principle(conn: sqlite3.Connection, principle_id: str) -> PrincipleTrace | None:
    """Trace a principle to its memories and their raw events.

    Args:
        conn: An open connection to the provenance DB.
        principle_id: The ``principles.id`` to trace.

    Returns:
        A :class:`PrincipleTrace` with nested memories/events, or ``None`` when
        no principle has that id. A principle that exists but has no memories
        (or memories with no events) returns a trace with empty lists, not
        ``None`` — the chain is thin, not absent.
    """
    prow = conn.execute(_PRINCIPLE_SQL, (principle_id,)).fetchone()
    if prow is None:
        return None
    rows = conn.execute(_LADDER_SQL, (principle_id,)).fetchall()
    confidence = prow["confidence"]
    return PrincipleTrace(
        principle_id=prow["id"],
        text=prow["text"],
        confidence=float(confidence) if confidence is not None else 0.0,
        memories=_group_rows(rows),
    )


def to_dict(trace: PrincipleTrace) -> dict:
    """Project a trace to a JSON-serialisable dict (for HTTP / ``--json``).

    Args:
        trace: The trace to project.

    Returns:
        A plain dict mirroring the dataclass shape.
    """
    return {
        "principle": {
            "id": trace.principle_id,
            "text": trace.text,
            "confidence": trace.confidence,
        },
        "memories": [
            {
                "memory_id": m.memory_id,
                "text": m.text,
                "source": m.source,
                "occurred_start": m.occurred_start,
                "events": [
                    {
                        "id": e.id,
                        "t_utc": e.t_utc,
                        "author_role": e.author_role,
                        "content": e.content,
                        "raw_ref": e.raw_ref,
                        "source": e.source,
                    }
                    for e in m.events
                ],
            }
            for m in trace.memories
        ],
    }
