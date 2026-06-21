"""Materialise the principle->memory->raw provenance ladder into recall.db.

The pipeline writes three JSON artifacts that already encode the full provenance
chain, but each lives in its own file and an agent would have to load and join
them in memory:

    principles.json / principles.merged.json  ->  derived_from: [memory_id, ...]
    bank_snapshot.json                         ->  memory_id -> raw_events[{id,...}]
    recall.db events table                     ->  the raw rows

This script folds those into ``recall.db`` as relational tables so a single SQL
hop walks each layer:

    principles            (id, text, confidence)
    principle_memories    (principle_id, memory_id)      <- principle -> memory
    edges                 (id, src_principle_id, dst_principle_id, relation)
    edge_memories         (edge_id, memory_id)           <- edge      -> memory
    memories              (memory_id, text, document_id, source, ...)
    memory_events         (memory_id, event_id)          <- memory    -> events

``memory_events.event_id`` references the existing ``events(id)`` rows, so the
ladder bottoms out at ground-truth raw data already in the same DB. An agent
handed a principle id can walk principle_memories -> memory_events -> events with
plain joins; no JSON parsing, no Hindsight boot.

Idempotent: re-running clears and rewrites the principle-layer tables (it never
touches ``events`` / ``capsules`` / ``media``).

Run::

    PYTHONPATH=src .venv/bin/python scripts/load_principles_db.py

No network, no OpenRouter, no Hindsight. Pure file -> SQLite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from loguru import logger

from core.logging import configure_logging

DEFAULT_DB_PATH = Path("data/recall.db")
DEFAULT_PRINCIPLES = Path("data/principles.json")
DEFAULT_EDGES = Path("data/edges.json")
DEFAULT_SNAPSHOT = Path("data/bank_snapshot.json")

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

#: Tables this loader owns and rewrites; ``events`` / ``capsules`` / ``media`` are
#: not in the list and are never touched.
_OWNED_TABLES = (
    "principle_memories",
    "edge_memories",
    "memory_events",
    "edges",
    "principles",
    "memories",
)


def _edge_id(src: str, dst: str, relation: str) -> str:
    """Return a stable id for an edge (edges.json has no id field).

    Args:
        src: Source principle id.
        dst: Destination principle id.
        relation: Edge relation (supports / refines / contradicts).

    Returns:
        A deterministic SHA-256 hex id over the triple.
    """
    return hashlib.sha256(f"{src}|{dst}|{relation}".encode()).hexdigest()


def _load_json(path: Path) -> list[dict]:
    """Load a JSON array file, failing loudly if missing or malformed."""
    if not path.exists():
        raise FileNotFoundError(f"required artifact not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array in {path}, got {type(data).__name__}")
    return data


def _reset_owned_tables(cur: sqlite3.Cursor) -> None:
    """Drop the principle-layer tables so a reload is a clean rewrite.

    Only tables this loader owns are dropped; raw-data tables are left intact.
    """
    for table in _OWNED_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
    cur.executescript(_SCHEMA)


def _insert_memories(cur: sqlite3.Cursor, snapshot: list[dict]) -> tuple[int, int]:
    """Insert memory rows and their memory->event links from the bank snapshot.

    Args:
        cur: Open cursor.
        snapshot: Records from bank_snapshot.json.

    Returns:
        (memory_count, memory_event_link_count).
    """
    known_events = {r[0] for r in cur.execute("SELECT id FROM events")}
    mem_count = 0
    link_count = 0
    skipped_events: set[str] = set()

    for rec in snapshot:
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
            "{} raw_event ids in the snapshot are absent from events table "
            "(skipped these memory->event links)",
            len(skipped_events),
        )
    return mem_count, link_count


def _insert_principles(cur: sqlite3.Cursor, principles: list[dict]) -> tuple[int, int]:
    """Insert principle rows and their principle->memory links.

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
            "{} principle derived_from memory_ids are not in the snapshot "
            "(provenance gap — skipped these links)",
            len(dangling),
        )
    return p_count, link_count


def _insert_edges(cur: sqlite3.Cursor, edges: list[dict]) -> tuple[int, int]:
    """Insert edge rows and their edge->memory links.

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
        edge_id = _edge_id(src, dst, relation)
        cur.execute(
            "INSERT OR REPLACE INTO edges "
            "(id, src_principle_id, dst_principle_id, relation) VALUES (?, ?, ?, ?)",
            (edge_id, src, dst, relation),
        )
        e_count += 1
        for memory_id in edge.get("derived_from", []):
            if memory_id not in known_memories:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO edge_memories (edge_id, memory_id) VALUES (?, ?)",
                (edge_id, memory_id),
            )
            link_count += 1

    if dangling_principles:
        logger.warning(
            "{} edge endpoint principle ids are not in principles.json "
            "(skipped these edges)",
            len(dangling_principles),
        )
    return e_count, link_count


def main() -> None:
    """Load the three JSON artifacts into recall.db's provenance tables."""
    configure_logging()

    ap = argparse.ArgumentParser(description="Load principles/edges/memories into recall.db.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="recall.db path.")
    ap.add_argument("--principles", type=Path, default=DEFAULT_PRINCIPLES)
    ap.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = ap.parse_args()

    if not args.db.exists():
        raise FileNotFoundError(
            f"{args.db} not found — run the build/retain pipeline first so the "
            "events table exists (memory_events references it)."
        )

    principles = _load_json(args.principles)
    edges = _load_json(args.edges)
    snapshot = _load_json(args.snapshot)
    logger.info(
        "loaded artifacts: {} principles, {} edges, {} snapshot memories",
        len(principles),
        len(edges),
        len(snapshot),
    )

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        cur = conn.cursor()
        _reset_owned_tables(cur)
        mem_count, mem_links = _insert_memories(cur, snapshot)
        p_count, p_links = _insert_principles(cur, principles)
        e_count, e_links = _insert_edges(cur, edges)
        conn.commit()
    finally:
        conn.close()

    logger.info("memories: {} rows, {} memory->event links", mem_count, mem_links)
    logger.info("principles: {} rows, {} principle->memory links", p_count, p_links)
    logger.info("edges: {} rows, {} edge->memory links", e_count, e_links)
    logger.info("done -> {}", args.db)


if __name__ == "__main__":
    main()
