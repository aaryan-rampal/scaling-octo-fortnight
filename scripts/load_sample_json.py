"""Build data/derek_handoff/derek_sample.db from a JSON export of the slice.

The handoff sometimes arrives as JSON (one key per table) rather than the
SQLite file. This rebuilds the ``.db`` the read path expects, with the schema
from ``data/derek_handoff/SCHEMA.md``. Idempotent: it recreates the file.

Run:
    .venv/bin/python scripts/load_sample_json.py <path-to-derek_sample.json>
    # default output: data/derek_handoff/derek_sample.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DEFAULT_OUT = Path("data/derek_handoff/derek_sample.db")

# Schema per data/derek_handoff/SCHEMA.md. Tables not populated by the export
# (capsules/media) are created empty for fidelity with recall.db.
_SCHEMA = """
CREATE TABLE events (
    id TEXT PRIMARY KEY, t_utc TEXT, author_role TEXT, content TEXT,
    thread_id TEXT, reply_to TEXT, raw_ref TEXT, source TEXT,
    content_sha TEXT, additional_data TEXT
);
CREATE TABLE capsules (
    id TEXT PRIMARY KEY, created_at TEXT, place_name TEXT, lat REAL, lng REAL
);
CREATE TABLE media (
    id TEXT PRIMARY KEY, capsule_id TEXT, kind TEXT, file_path TEXT, mime TEXT,
    byte_size INTEGER, exif_t TEXT, exif_lat REAL, exif_lng REAL
);
CREATE TABLE principles (id TEXT PRIMARY KEY, text TEXT, confidence REAL);
CREATE TABLE edges (
    id TEXT PRIMARY KEY, src_principle_id TEXT, dst_principle_id TEXT, relation TEXT
);
CREATE TABLE memories (
    memory_id TEXT PRIMARY KEY, text TEXT, document_id TEXT, source TEXT,
    fact_type TEXT, entities TEXT, occurred_start TEXT, tags TEXT
);
CREATE TABLE principle_memories (principle_id TEXT, memory_id TEXT);
CREATE TABLE edge_memories (edge_id TEXT, memory_id TEXT);
CREATE TABLE memory_events (memory_id TEXT, event_id TEXT);
"""

TABLES = [
    "events", "capsules", "media", "principles", "edges", "memories",
    "principle_memories", "edge_memories", "memory_events",
]


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    """Insert rows into table using their own keys as columns; returns count."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join("?" * len(cols))
    conn.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build derek_sample.db from JSON export.")
    ap.add_argument("json_path", type=Path, help="Path to derek_sample.json.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output .db path.")
    args = ap.parse_args()

    data = json.loads(args.json_path.read_text(encoding="utf-8"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()

    conn = sqlite3.connect(args.out)
    try:
        conn.executescript(_SCHEMA)
        counts = {t: _insert(conn, t, data.get(t, [])) for t in TABLES}
        conn.commit()
    finally:
        conn.close()

    print(f"wrote {args.out}")
    for t in TABLES:
        print(f"  {t}: {counts[t]}")


if __name__ == "__main__":
    main()
