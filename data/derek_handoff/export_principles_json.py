"""Export recall_new.db -> a rich principles.json for the multi-layer graph.

Emits the FULL provenance graph the UI renders:
  - principles (nodes, sized by confidence + trace depth)
  - edges      (typed links, each carrying its shared-memory evidence)
  - memories   (a second tier of nodes, linked to their principles)
  - raw events (a capped sample per memory + the true total, for drill-down)

Self-contained: writes a single principles.json at the repo root, served
statically. No backend, no live queries.

Run:  .venv/bin/python data/derek_handoff/export_principles_json.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Per-user principle sets. `python export_principles_json.py <user>` exports just
# that user; with no args it exports all. Each maps a source DB → the JSON the
# web app fetches (principles.<user>.json), picked by the login username.
USERS = {
    "aaryan": (HERE / "recall_new.db",        ROOT / "principles.aaryan.json"),
    "selin":  (HERE / "recall_expansive.db",  ROOT / "principles.selin.json"),
}
# The default file the app loads when no/unknown user (kept = aaryan's set).
DEFAULT_OUT = ROOT / "principles.json"

#: Cap raw events embedded per memory (keeps the JSON small; the true total is
#: always reported alongside so the UI can say "showing 8 of 162").
EVENTS_PER_MEMORY = 8


def principle_rows(db: sqlite3.Connection) -> list[dict]:
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
        # which memory ids back this principle
        mems = [
            m[0] for m in db.execute(
                "SELECT memory_id FROM principle_memories WHERE principle_id=?", (r[0],)
            )
        ]
        out.append({
            "id": r[0], "short": r[0][:12], "text": r[1], "confidence": r[2],
            "n_memories": r[3], "n_events": r[4], "memory_ids": mems,
        })
    return out


def edge_rows(db: sqlite3.Connection) -> list[dict]:
    q = """
    SELECT ed.id, ed.src_principle_id, ed.dst_principle_id, ed.relation,
           COUNT(DISTINCT em.memory_id) AS n_memories,
           COUNT(DISTINCT me.event_id)  AS n_events
    FROM edges ed
    LEFT JOIN edge_memories em ON em.edge_id   = ed.id
    LEFT JOIN memory_events me ON me.memory_id = em.memory_id
    GROUP BY ed.id
    """
    out = []
    for r in db.execute(q):
        mems = [
            m[0] for m in db.execute(
                "SELECT memory_id FROM edge_memories WHERE edge_id=?", (r[0],)
            )
        ]
        out.append({
            "id": r[0], "src": r[1], "dst": r[2], "relation": r[3],
            "n_memories": r[4], "n_events": r[5], "memory_ids": mems,
        })
    return out


def memory_rows(db: sqlite3.Connection, memory_ids: list[str]) -> list[dict]:
    """Each linked memory + a capped sample of the raw events behind it."""
    out = []
    for mid in memory_ids:
        m = db.execute(
            "SELECT memory_id, text, source, fact_type, entities, occurred_start "
            "FROM memories WHERE memory_id=?", (mid,)
        ).fetchone()
        if m is None:
            continue
        n_events = db.execute(
            "SELECT COUNT(*) FROM memory_events WHERE memory_id=?", (mid,)
        ).fetchone()[0]
        events = [
            {"id": e[0], "t_utc": e[1], "author_role": e[2], "source": e[3],
             "raw_ref": e[4], "content": (e[5] or "")[:280]}
            for e in db.execute(
                "SELECT e.id, e.t_utc, e.author_role, e.source, e.raw_ref, e.content "
                "FROM memory_events me JOIN events e ON e.id = me.event_id "
                "WHERE me.memory_id=? ORDER BY e.t_utc LIMIT ?",
                (mid, EVENTS_PER_MEMORY),
            )
        ]
        out.append({
            "id": m[0], "short": m[0][:8], "text": m[1], "source": m[2],
            "fact_type": m[3], "entities": (m[4] or ""), "occurred_start": m[5],
            "n_events": n_events, "events": events,
        })
    return out


def export_one(db_path: Path, out_path: Path) -> None:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    db = sqlite3.connect(db_path)
    principles = principle_rows(db)
    edges = edge_rows(db)
    linked = {mid for p in principles for mid in p["memory_ids"]}
    linked |= {mid for e in edges for mid in e["memory_ids"]}
    memories = memory_rows(db, sorted(linked))
    payload = {
        "principles": principles, "edges": edges, "memories": memories,
        "generated_from": db_path.name,
    }
    db.close()
    out_path.write_text(json.dumps(payload))  # compact
    total = sum(m["n_events"] for m in memories)
    print(f"wrote {out_path.name} — {len(principles)} principles, "
          f"{len(edges)} edges, {len(memories)} memories ({total} raw events)")


def main() -> None:
    # optional: a single user name to export just that set
    want = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if want and want not in USERS:
        raise SystemExit(f"unknown user {want!r}; known: {', '.join(USERS)}")
    for user, (db_path, out_path) in USERS.items():
        if want and user != want:
            continue
        export_one(db_path, out_path)
        # keep principles.json (the default) in sync with aaryan's set
        if user == "aaryan" and (not want or want == "aaryan"):
            export_one(db_path, DEFAULT_OUT)


if __name__ == "__main__":
    main()
