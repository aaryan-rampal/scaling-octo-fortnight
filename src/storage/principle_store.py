"""Write the principle->memory->raw provenance ladder into recall.db directly.

This is the shared write path for the principle layer. Both the live pipeline
stages (``link`` minting merged principles + edges, ``dump`` materialising the
memory layer) and the standalone JSON loader (``scripts/load_principles_db.py``,
a fallback) call into here so the table schema, reset semantics, and insert
logic live in exactly one place.

The ladder it materialises::

    principles            (id, text, confidence)
    principle_memories    (principle_id, memory_id)      <- principle -> memory
    edges                 (id, src_principle_id, dst_principle_id, relation)
    edge_memories         (edge_id, memory_id)           <- edge      -> memory
    memories              (memory_id, text, document_id, source, ...)
    memory_events         (memory_id, event_id)          <- memory    -> events

``memory_events.event_id`` references the existing ``events(id)`` rows, so the
ladder bottoms out at ground-truth raw data already in the same DB.

Reset semantics: :meth:`PrincipleStore.reset` drops and recreates ONLY the six
derived tables it owns inside one transaction. The raw tables (``events`` /
``capsules`` / ``media``) are never named and never touched. A re-run that
writes fewer principles than the prior run therefore ends with exactly the new
count — no stale rows survive.

No network, no OpenRouter, no Hindsight. Pure data -> SQLite.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

from loguru import logger

#: Default on-disk location of recall.db (mirrors ``storage.store``).
DEFAULT_DB_PATH = Path("data/recall.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS principles (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    confidence  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id       TEXT PRIMARY KEY,
    text            TEXT NOT NULL,
    document_id     TEXT,
    source          TEXT,
    fact_type       TEXT,
    entities        TEXT,
    occurred_start  TEXT,
    tags            TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS edges (
    id                  TEXT PRIMARY KEY,
    src_principle_id    TEXT NOT NULL REFERENCES principles(id),
    dst_principle_id    TEXT NOT NULL REFERENCES principles(id),
    relation            TEXT NOT NULL
);

-- principle -> memory: the first hop down the ladder.
CREATE TABLE IF NOT EXISTS principle_memories (
    principle_id    TEXT NOT NULL REFERENCES principles(id) ON DELETE CASCADE,
    memory_id       TEXT NOT NULL,
    PRIMARY KEY (principle_id, memory_id)
);

-- edge -> memory: edges carry their own derived_from provenance.
CREATE TABLE IF NOT EXISTS edge_memories (
    edge_id     TEXT NOT NULL REFERENCES edges(id) ON DELETE CASCADE,
    memory_id   TEXT NOT NULL,
    PRIMARY KEY (edge_id, memory_id)
);

-- memory -> raw event: the bottom hop into the existing events table.
CREATE TABLE IF NOT EXISTS memory_events (
    memory_id   TEXT NOT NULL REFERENCES memories(memory_id) ON DELETE CASCADE,
    event_id    TEXT NOT NULL REFERENCES events(id),
    PRIMARY KEY (memory_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_principle_memories_memory ON principle_memories(memory_id);
CREATE INDEX IF NOT EXISTS idx_edge_memories_memory ON edge_memories(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_events_event ON memory_events(event_id);
"""

#: All derived tables this store owns; ``events`` / ``capsules`` / ``media`` are
#: not in the list and are never touched. Drop order respects FK dependencies.
_OWNED_TABLES = (
    "principle_memories",
    "edge_memories",
    "memory_events",
    "edges",
    "principles",
    "memories",
)

#: The memory layer (dump stage owns these): memory rows + memory->event links.
_MEMORY_TABLES = ("memory_events", "memories")

#: The principle layer (link stage owns these): principle/edge rows + their
#: memory links. ``principle_memories`` / ``edge_memories`` reference memory_ids
#: as plain columns (no FK), so this group can be reset and rewritten on its own
#: as long as the memory layer was written first (dump runs before link).
_PRINCIPLE_TABLES = ("principle_memories", "edge_memories", "edges", "principles")


def edge_id(src: str, dst: str, relation: str) -> str:
    """Return a stable id for an edge (edges have no natural id field).

    Args:
        src: Source principle id.
        dst: Destination principle id.
        relation: Edge relation (supports / refines / contradicts / ...).

    Returns:
        A deterministic SHA-256 hex id over the triple.
    """
    return hashlib.sha256(f"{src}|{dst}|{relation}".encode()).hexdigest()


class PrincipleStore:
    """Owns the six derived principle-layer tables in recall.db.

    Wraps a single ``sqlite3`` connection with foreign keys on. All mutating
    methods are designed to run inside one outer transaction so a write is
    all-or-nothing: use :meth:`write` for the common case (reset + insert in one
    commit), or compose :meth:`reset` / the ``insert_*`` methods under your own
    transaction.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Wrap an open connection (foreign keys are enabled here).

        Args:
            conn: An open sqlite3 connection to recall.db. The caller owns its
                lifecycle (this class never closes it).
        """
        self._conn = conn
        self._conn.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def open(cls, db_path: str | Path = DEFAULT_DB_PATH) -> PrincipleStore:
        """Open recall.db at ``db_path`` and wrap it.

        Args:
            db_path: Path to the SQLite file. Must already exist — the principle
                layer references ``events(id)``, so the raw store has to be there.

        Returns:
            A ``PrincipleStore`` over a fresh connection the caller must close.

        Raises:
            FileNotFoundError: If ``db_path`` does not exist.
        """
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found — run the build/retain pipeline first so the "
                "events table exists (memory_events references it)."
            )
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        """Close the wrapped connection."""
        self._conn.close()

    def reset(self, tables: Sequence[str] = _OWNED_TABLES) -> None:
        """Drop the named owned tables, then (re)create the full schema.

        Only tables this store owns may be passed. ``events`` / ``capsules`` /
        ``media`` are never in the owned set, so a reset can never lose raw data.
        The schema is re-applied with ``CREATE TABLE IF NOT EXISTS`` so dropping a
        subset (e.g. just the principle layer) leaves the rest intact. Call inside
        a transaction (e.g. via one of the ``write_*`` methods).

        Args:
            tables: The owned tables to drop. Defaults to all of them.

        Raises:
            ValueError: If any table is not one this store owns.
        """
        unknown = set(tables) - set(_OWNED_TABLES)
        if unknown:
            raise ValueError(f"refusing to reset tables this store does not own: {sorted(unknown)}")
        cur = self._conn.cursor()
        for table in tables:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.executescript(_SCHEMA)

    def write(
        self,
        principles: Sequence[Mapping],
        edges: Sequence[Mapping],
        memories: Sequence[Mapping],
    ) -> dict[str, int]:
        """Reset the derived tables and write the full ladder in one transaction.

        All-or-nothing: a reset + every insert commit together, so a failure
        rolls back to the prior run's tables rather than a half-written state.

        Args:
            principles: Principle dicts with ``id`` / ``text`` / ``confidence`` /
                ``derived_from`` (list of memory_ids).
            edges: Edge dicts with ``src`` / ``dst`` / ``relation`` /
                ``derived_from``.
            memories: Memory dicts with ``memory_id`` / ``text`` / ... /
                ``raw_events`` (list of ``{id: ...}`` raw-event projections).

        Returns:
            Row/link counts keyed by ``memories`` / ``memory_events`` /
            ``principles`` / ``principle_memories`` / ``edges`` / ``edge_memories``.
        """
        try:
            self.reset()
            cur = self._conn.cursor()
            mem_count, mem_links = self._insert_memories(cur, memories)
            p_count, p_links = self._insert_principles(cur, principles)
            e_count, e_links = self._insert_edges(cur, edges)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        counts = {
            "memories": mem_count,
            "memory_events": mem_links,
            "principles": p_count,
            "principle_memories": p_links,
            "edges": e_count,
            "edge_memories": e_links,
        }
        logger.info("principle layer written: {}", counts)
        return counts

    def write_memory_layer(self, memories: Sequence[Mapping]) -> dict[str, int]:
        """Reset and rewrite only the memory layer (dump stage's slice).

        Resets ``memories`` + ``memory_events`` in one transaction and rewrites
        them; the principle/edge tables are untouched. This is the DB-direct path
        for ``scripts/dump_bank.py`` — it runs before ``link``, so the principle
        layer it leaves alone is rewritten later against these fresh memories.

        Args:
            memories: Memory records (each may carry ``raw_events``).

        Returns:
            Counts keyed by ``memories`` / ``memory_events``.
        """
        try:
            self.reset(_MEMORY_TABLES)
            cur = self._conn.cursor()
            mem_count, mem_links = self._insert_memories(cur, memories)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        counts = {"memories": mem_count, "memory_events": mem_links}
        logger.info("memory layer written: {}", counts)
        return counts

    def write_principle_layer(
        self, principles: Sequence[Mapping], edges: Sequence[Mapping]
    ) -> dict[str, int]:
        """Reset and rewrite only the principle layer (link stage's slice).

        Resets the four principle/edge tables in one transaction and rewrites
        them, validating ``derived_from`` ids against the memory layer the dump
        stage already wrote. The memory tables are untouched. This is the
        DB-direct path for ``scripts/link_principles.py``.

        Args:
            principles: Canonical (merged) principle records.
            edges: Edge records.

        Returns:
            Counts keyed by ``principles`` / ``principle_memories`` / ``edges`` /
            ``edge_memories``.
        """
        try:
            self.reset(_PRINCIPLE_TABLES)
            cur = self._conn.cursor()
            p_count, p_links = self._insert_principles(cur, principles)
            e_count, e_links = self._insert_edges(cur, edges)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        counts = {
            "principles": p_count,
            "principle_memories": p_links,
            "edges": e_count,
            "edge_memories": e_links,
        }
        logger.info("principle layer written: {}", counts)
        return counts

    def _insert_memories(
        self, cur: sqlite3.Cursor, memories: Sequence[Mapping]
    ) -> tuple[int, int]:
        """Insert memory rows and their memory->event links.

        Args:
            cur: Open cursor.
            memories: Memory records (each may carry ``raw_events``).

        Returns:
            (memory_count, memory_event_link_count).
        """
        known_events = {r[0] for r in cur.execute("SELECT id FROM events")}
        mem_count = 0
        link_count = 0
        skipped_events: set[str] = set()

        for rec in memories:
            memory_id = rec["memory_id"]
            cur.execute(
                "INSERT OR REPLACE INTO memories "
                "(memory_id, text, document_id, source, fact_type, entities, "
                " occurred_start, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    rec.get("text", ""),
                    rec.get("document_id"),
                    rec.get("source"),
                    rec.get("fact_type"),
                    rec.get("entities"),
                    rec.get("occurred_start"),
                    json.dumps(rec.get("tags", []), ensure_ascii=False),
                ),
            )
            mem_count += 1
            for event in rec.get("raw_events", []):
                event_id = event["id"]
                if event_id not in known_events:
                    skipped_events.add(event_id)
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO memory_events (memory_id, event_id) VALUES (?, ?)",
                    (memory_id, event_id),
                )
                link_count += 1

        if skipped_events:
            logger.warning(
                "{} raw_event ids are absent from the events table "
                "(skipped these memory->event links)",
                len(skipped_events),
            )
        return mem_count, link_count

    def _insert_principles(
        self, cur: sqlite3.Cursor, principles: Sequence[Mapping]
    ) -> tuple[int, int]:
        """Insert principle rows and their principle->memory links.

        Args:
            cur: Open cursor.
            principles: Principle records with ``derived_from`` memory_ids.

        Returns:
            (principle_count, principle_memory_link_count).
        """
        known_memories = {r[0] for r in cur.execute("SELECT memory_id FROM memories")}
        p_count = 0
        link_count = 0
        dangling: set[str] = set()

        for p in principles:
            cur.execute(
                "INSERT OR REPLACE INTO principles (id, text, confidence) VALUES (?, ?, ?)",
                (p["id"], p["text"], float(p["confidence"])),
            )
            p_count += 1
            for memory_id in p.get("derived_from", []):
                if memory_id not in known_memories:
                    dangling.add(memory_id)
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO principle_memories (principle_id, memory_id) "
                    "VALUES (?, ?)",
                    (p["id"], memory_id),
                )
                link_count += 1

        if dangling:
            logger.warning(
                "{} principle derived_from memory_ids are not in the memory layer "
                "(provenance gap — skipped these links)",
                len(dangling),
            )
        return p_count, link_count

    def _insert_edges(self, cur: sqlite3.Cursor, edges: Sequence[Mapping]) -> tuple[int, int]:
        """Insert edge rows and their edge->memory links.

        Args:
            cur: Open cursor.
            edges: Edge records with ``src`` / ``dst`` / ``relation`` /
                ``derived_from``.

        Returns:
            (edge_count, edge_memory_link_count).
        """
        known_principles = {r[0] for r in cur.execute("SELECT id FROM principles")}
        known_memories = {r[0] for r in cur.execute("SELECT memory_id FROM memories")}
        e_count = 0
        link_count = 0
        dangling_principles: set[str] = set()

        for edge in edges:
            src, dst, relation = edge["src"], edge["dst"], edge["relation"]
            if src not in known_principles or dst not in known_principles:
                dangling_principles.update({src, dst} - known_principles)
                continue
            eid = edge_id(src, dst, relation)
            cur.execute(
                "INSERT OR REPLACE INTO edges "
                "(id, src_principle_id, dst_principle_id, relation) VALUES (?, ?, ?, ?)",
                (eid, src, dst, relation),
            )
            e_count += 1
            for memory_id in edge.get("derived_from", []):
                if memory_id not in known_memories:
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO edge_memories (edge_id, memory_id) VALUES (?, ?)",
                    (eid, memory_id),
                )
                link_count += 1

        if dangling_principles:
            logger.warning(
                "{} edge endpoint principle ids are not in the principle set "
                "(skipped these edges)",
                len(dangling_principles),
            )
        return e_count, link_count
