"""Export derek_sample.db -> a static principles.json for the web UI graph.

Reads the fully-traceable sample slice and writes a single JSON file the frontend
fetches to render the principle graph (nodes sized by confidence + raw-event
depth, connected by typed edges). Fully static: no backend, no live queries.

Output shape (consumed by the principles graph view):
  {
    "principles": [
      { "id", "short", "text", "confidence", "n_memories", "n_events" }, ...
    ],
    "edges": [
      { "id", "src", "dst", "relation", "n_events" }, ...
    ],
    "generated_from": "derek_sample.db"
  }

Run:  .venv/bin/python data/derek_handoff/export_principles_json.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "derek_sample.db"
# Write next to the static web app so it's fetchable at /principles.json.
OUT = HERE.parents[1] / "principles.json"


def principle_rows(db: sqlite3.Connection) -> list[dict]:
    """Principles + their trace depth (distinct memories / raw events)."""
    q = """
    SELECT p.id, p.text, p.confidence,
           COUNT(DISTINCT pm.memory_id) AS n_memories,
           COUNT(DISTINCT me.event_id)  AS n_events
    FROM principles p
    LEFT JOIN principle_memories pm ON pm.principle_id = p.id
    LEFT JOIN memory_events     me ON me.memory_id    = pm.memory_id
    GROUP BY p.id
    ORDER BY p.confidence DESC
    """
    out = []
    for r in db.execute(q):
        out.append({
            "id": r[0],
            "short": r[0][:12],
            "text": r[1],
            "confidence": r[2],
            "n_memories": r[3],
            "n_events": r[4],
        })
    return out


def edge_rows(db: sqlite3.Connection) -> list[dict]:
    """Typed edges + how many raw events justify each connection."""
    q = """
    SELECT ed.id, ed.src_principle_id, ed.dst_principle_id, ed.relation,
           COUNT(DISTINCT me.event_id) AS n_events
    FROM edges ed
    LEFT JOIN edge_memories em ON em.edge_id   = ed.id
    LEFT JOIN memory_events me ON me.memory_id = em.memory_id
    GROUP BY ed.id
    """
    out = []
    for r in db.execute(q):
        out.append({
            "id": r[0],
            "src": r[1],
            "dst": r[2],
            "relation": r[3],
            "n_events": r[4],
        })
    return out


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"sample DB not found: {DB}")
    db = sqlite3.connect(DB)
    payload = {
        "principles": principle_rows(db),
        "edges": edge_rows(db),
        "generated_from": DB.name,
    }
    db.close()
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUT} — {len(payload['principles'])} principles, "
          f"{len(payload['edges'])} edges")


if __name__ == "__main__":
    main()
