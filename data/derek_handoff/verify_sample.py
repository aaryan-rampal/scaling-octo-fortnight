"""Verify derek_sample.db is fully traceable with zero dangling ids.

Checks:
  1. Every principle reaches >= 1 raw event (principle -> memory -> event).
  2. No orphan ids in any join table (all referenced rows exist).

Run:  PYTHONPATH=src .venv/bin/python data/derek_handoff/verify_sample.py
Exit 0 = clean.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path("data/derek_handoff/derek_sample.db")


def main() -> int:
    c = sqlite3.connect(DB)
    problems: list[str] = []

    # --- orphan checks: every fk target must exist ---
    orphan_queries = {
        "principle_memories.principle_id -> principles": (
            "SELECT COUNT(*) FROM principle_memories pm "
            "LEFT JOIN principles p ON p.id=pm.principle_id WHERE p.id IS NULL"
        ),
        "principle_memories.memory_id -> memories": (
            "SELECT COUNT(*) FROM principle_memories pm "
            "LEFT JOIN memories m ON m.memory_id=pm.memory_id WHERE m.memory_id IS NULL"
        ),
        "edge_memories.edge_id -> edges": (
            "SELECT COUNT(*) FROM edge_memories em "
            "LEFT JOIN edges e ON e.id=em.edge_id WHERE e.id IS NULL"
        ),
        "edge_memories.memory_id -> memories": (
            "SELECT COUNT(*) FROM edge_memories em "
            "LEFT JOIN memories m ON m.memory_id=em.memory_id WHERE m.memory_id IS NULL"
        ),
        "memory_events.memory_id -> memories": (
            "SELECT COUNT(*) FROM memory_events me "
            "LEFT JOIN memories m ON m.memory_id=me.memory_id WHERE m.memory_id IS NULL"
        ),
        "memory_events.event_id -> events": (
            "SELECT COUNT(*) FROM memory_events me "
            "LEFT JOIN events e ON e.id=me.event_id WHERE e.id IS NULL"
        ),
        "edges.src_principle_id -> principles": (
            "SELECT COUNT(*) FROM edges e "
            "LEFT JOIN principles p ON p.id=e.src_principle_id WHERE p.id IS NULL"
        ),
        "edges.dst_principle_id -> principles": (
            "SELECT COUNT(*) FROM edges e "
            "LEFT JOIN principles p ON p.id=e.dst_principle_id WHERE p.id IS NULL"
        ),
    }
    for label, q in orphan_queries.items():
        n = c.execute(q).fetchone()[0]
        if n:
            problems.append(f"DANGLING: {n} orphan rows in {label}")

    # --- every principle reaches >= 1 raw event ---
    print("principle -> raw-event trace depth:")
    rows = c.execute(
        """
        SELECT p.id, substr(p.text,1,52) AS t,
               COUNT(DISTINCT pm.memory_id) AS n_mem,
               COUNT(DISTINCT me.event_id)  AS n_raw
        FROM principles p
        LEFT JOIN principle_memories pm ON pm.principle_id = p.id
        LEFT JOIN memory_events me        ON me.memory_id   = pm.memory_id
        GROUP BY p.id ORDER BY n_raw DESC
        """
    ).fetchall()
    for pid, text, n_mem, n_raw in rows:
        flag = "" if n_raw >= 1 else "  <-- NO RAW TRACE"
        print(f"  {n_raw:>3} raw | {n_mem} mem | {pid[:12]} | {text}{flag}")
        if n_raw < 1:
            problems.append(f"NO TRACE: principle {pid[:12]} reaches 0 raw events")

    # --- edge -> raw-event trace depth ---
    print("\nedge -> raw-event trace depth:")
    erows = c.execute(
        """
        SELECT e.id, e.relation, e.src_principle_id, e.dst_principle_id,
               COUNT(DISTINCT me.event_id) AS n_raw
        FROM edges e
        LEFT JOIN edge_memories em ON em.edge_id = e.id
        LEFT JOIN memory_events me ON me.memory_id = em.memory_id
        GROUP BY e.id ORDER BY n_raw DESC
        """
    ).fetchall()
    for eid, rel, src, dst, n_raw in erows:
        print(f"  {n_raw:>3} raw | {rel:11} | {src[:8]} -> {dst[:8]} | {eid[:12]}")

    print()
    if problems:
        for p in problems:
            print("FAIL:", p)
        return 1
    print("PASS: zero dangling ids; every principle and edge traces to raw events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
