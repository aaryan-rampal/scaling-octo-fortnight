"""Build derek_sample.db: a fully-traceable vertical slice of recall.db.

Picks 5 principles, then copies their COMPLETE downward closure
(principles -> edges -> memories -> events) into a fresh SQLite DB with the
same schema. Every id in the slice resolves to a real row -- no dangling ids.

Run:  PYTHONPATH=src .venv/bin/python data/derek_handoff/build_sample.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SRC = Path("data/recall.db")
DST = Path("data/derek_handoff/derek_sample.db")

# Chosen by prefix; resolved to full ids at runtime. These 5 form a connected
# edge subgraph (research cluster + decision-theory) AND each carries a deep
# raw-event trace, so Derek gets both principle->raw and edge->raw walks.
CHOSEN_PREFIXES = [
    "a9476af4e29c",  # align research choices with long-term normative goal (22 raw)
    "92c6dd7f4731",  # deliberate, informed academic decisions   (hub, 22 raw)
    "b57296638217",  # build strong academic/professional foundation (22 raw)
    "ed864bf62740",  # prioritize AI-safety research directions   (22 raw)
    "b15f78146dc7",  # rigorous decision-theoretic reasoning      (2 raw)
]

TABLES = [
    "events",
    "capsules",
    "media",
    "principles",
    "edges",
    "memories",
    "principle_memories",
    "edge_memories",
    "memory_events",
]


def resolve_ids(src: sqlite3.Connection) -> list[str]:
    out = []
    for pref in CHOSEN_PREFIXES:
        row = src.execute(
            "SELECT id FROM principles WHERE id LIKE ?", (pref + "%",)
        ).fetchone()
        if row is None:
            raise SystemExit(f"principle prefix not found: {pref}")
        out.append(row[0])
    return out


def copy_schema(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    for table in TABLES:
        ddl = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        dst.execute(ddl)
    dst.commit()


def copy_rows(
    src: sqlite3.Connection, dst: sqlite3.Connection, table: str, ids: list[str], col: str
) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    rows = src.execute(
        f"SELECT * FROM {table} WHERE {col} IN ({placeholders})", ids
    ).fetchall()
    if rows:
        ncols = len(rows[0])
        dst.executemany(
            f"INSERT INTO {table} VALUES ({','.join('?' * ncols)})", rows
        )
    dst.commit()
    return len(rows)


def main() -> None:
    if DST.exists():
        DST.unlink()
    src = sqlite3.connect(SRC)
    dst = sqlite3.connect(DST)
    copy_schema(src, dst)

    principle_ids = resolve_ids(src)
    ph = ",".join("?" * len(principle_ids))

    # 1. internal edges (both endpoints in the chosen set)
    edge_rows = src.execute(
        f"SELECT id FROM edges WHERE src_principle_id IN ({ph}) "
        f"AND dst_principle_id IN ({ph})",
        principle_ids + principle_ids,
    ).fetchall()
    edge_ids = [r[0] for r in edge_rows]

    # 2. memory ids reachable from principles and from internal edges
    pm_mems = {
        r[0]
        for r in src.execute(
            f"SELECT memory_id FROM principle_memories WHERE principle_id IN ({ph})",
            principle_ids,
        )
    }
    em_mems: set[str] = set()
    if edge_ids:
        eph = ",".join("?" * len(edge_ids))
        em_mems = {
            r[0]
            for r in src.execute(
                f"SELECT memory_id FROM edge_memories WHERE edge_id IN ({eph})",
                edge_ids,
            )
        }
    memory_ids = sorted(pm_mems | em_mems)

    # 3. event ids reachable from those memories
    mph = ",".join("?" * len(memory_ids))
    event_ids = sorted(
        {
            r[0]
            for r in src.execute(
                f"SELECT event_id FROM memory_events WHERE memory_id IN ({mph})",
                memory_ids,
            )
        }
    )

    # copy in dependency order
    n_ev = copy_rows(src, dst, "events", event_ids, "id")
    n_pr = copy_rows(src, dst, "principles", principle_ids, "id")
    n_ed = copy_rows(src, dst, "edges", edge_ids, "id")
    n_me = copy_rows(src, dst, "memories", memory_ids, "memory_id")
    n_pm = copy_rows(src, dst, "principle_memories", principle_ids, "principle_id")
    n_em = copy_rows(src, dst, "edge_memories", edge_ids, "edge_id")
    n_mev = copy_rows(src, dst, "memory_events", memory_ids, "memory_id")
    # capsules/media are empty in source but schema is copied for completeness.

    print(
        f"events={n_ev} principles={n_pr} edges={n_ed} memories={n_me} "
        f"principle_memories={n_pm} edge_memories={n_em} memory_events={n_mev}"
    )
    src.close()
    dst.close()


if __name__ == "__main__":
    main()
