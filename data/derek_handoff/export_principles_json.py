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
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Per-user principle sets. `python export_principles_json.py <user>` exports just
# that user; with no args it exports all. Each maps a source DB → the JSON the
# web app fetches (principles.<user>.json), picked by the login username.
#
# `top_n` (optional): when a DB has no real edges, keep only the top-N strongest
# principles (confidence × log raw-event depth) and DERIVE similarity edges +
# clusters from their text, so the graph reads like the curated one. None = use
# the DB's own principles/edges as-is.
USERS = {
    "aaryan":      (HERE / "recall_new.db",        ROOT / "principles.aaryan.json",      None),
    # selin's curated sample: 6 principles with real edges + full trace (use as-is).
    "selin":       (HERE / "selin_sample.db",      ROOT / "principles.selin.json",       None),
    # a 3rd login: aaryan's expansive set, similarity-connected (top 40 by depth).
    "aaryan-full": (HERE / "recall_expansive.db",  ROOT / "principles.aaryan-full.json", 40),
}
# The default file the app loads when no/unknown user (kept = aaryan's set).
DEFAULT_OUT = ROOT / "principles.json"

#: similarity-edge tuning for derived graphs
SIM_KNN = 3        # connect each principle to its k most-similar others
SIM_MIN = 0.18     # …above this cosine, so weak links are dropped
N_CLUSTERS = 5     # thematic groups to color

_STOP = set((
    "you your the a an and or to of in on for with that this is are be as own into "
    "about over they them their it its make making value valuing seek seeking strive "
    "striving have has had your more most than then when while who what which not"
).split())


def _toks(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 3 and w not in _STOP]


def _tfidf(docs: dict[str, list[str]]) -> dict[str, dict[str, float]]:
    df: Counter = Counter()
    for ts in docs.values():
        df.update(set(ts))
    n = max(len(docs), 1)
    out = {}
    for pid, ts in docs.items():
        tf = Counter(ts)
        out[pid] = {w: c * math.log(n / (1 + df[w])) for w, c in tf.items()}
    return out


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    na = math.sqrt(sum(x * x for x in a.values()))
    nb = math.sqrt(sum(x * x for x in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def derive_edges_and_clusters(principles: list[dict]) -> list[dict]:
    """Connect similar principles (kNN over TF-IDF text) + assign cluster ids.

    Mutates each principle dict with a `cluster` field and returns the edge list
    (same shape as DB edges but relation="similar", no memory evidence).
    """
    docs = {p["id"]: _toks(p["text"]) for p in principles}
    vecs = _tfidf(docs)
    ids = list(docs)

    # kNN similarity edges (undirected, deduped)
    edges, seen = [], set()
    for a in ids:
        sims = sorted(((_cos(vecs[a], vecs[b]), b) for b in ids if b != a), reverse=True)
        for s, b in sims[:SIM_KNN]:
            if s < SIM_MIN:
                break
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"id": f"sim-{len(edges)}", "src": key[0], "dst": key[1],
                          "relation": "similar", "n_memories": 0, "n_events": 0,
                          "weight": round(s, 3), "memory_ids": []})

    # cluster via union-find over ALL positive-similarity links (not just the kNN
    # edges) so weakly-similar nodes still join a theme; then keep the largest
    # N_CLUSTERS groups and fold every smaller/singleton group into the cluster it
    # is most similar to — so we end with ~N colored themes, not dozens.
    parent = {pid: pid for pid in ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry
    all_sims = sorted(
        ((_cos(vecs[ids[i]], vecs[ids[j]]), ids[i], ids[j])
         for i in range(len(ids)) for j in range(i + 1, len(ids))),
        reverse=True,
    )
    for s, a, b in all_sims:
        if s < SIM_MIN:
            break
        union(a, b)

    from collections import defaultdict
    members = defaultdict(list)
    for pid in ids:
        members[find(pid)].append(pid)
    ordered = sorted(members.values(), key=len, reverse=True)
    big = ordered[:N_CLUSTERS]
    cluster_of = {pid: idx for idx, grp in enumerate(big) for pid in grp}

    # fold leftover nodes into the big cluster whose members they're most like
    centroids = []
    for grp in big:
        cen: dict[str, float] = defaultdict(float)
        for pid in grp:
            for w, v in vecs[pid].items():
                cen[w] += v
        centroids.append(cen)
    for grp in ordered[N_CLUSTERS:]:
        for pid in grp:
            best = max(range(len(big)), key=lambda c: _cos(vecs[pid], centroids[c]), default=0)
            cluster_of[pid] = best

    for p in principles:
        p["cluster"] = cluster_of.get(p["id"], 0)
    return edges

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


def export_one(db_path: Path, out_path: Path, top_n: int | None = None) -> None:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    db = sqlite3.connect(db_path)
    principles = principle_rows(db)
    edges = edge_rows(db)

    if top_n:
        # keep the strongest principles (confidence × log raw-event depth), then
        # DERIVE similarity edges + clusters so the graph reads like the curated one
        principles.sort(key=lambda p: -(p["confidence"] * math.log(p["n_events"] + 1)))
        principles = principles[:top_n]
        edges = derive_edges_and_clusters(principles)

    linked = {mid for p in principles for mid in p["memory_ids"]}
    linked |= {mid for e in edges for mid in e.get("memory_ids", [])}
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
    for user, (db_path, out_path, top_n) in USERS.items():
        if want and user != want:
            continue
        export_one(db_path, out_path, top_n)
        # keep principles.json (the default) in sync with aaryan's set
        if user == "aaryan" and (not want or want == "aaryan"):
            export_one(db_path, DEFAULT_OUT)


if __name__ == "__main__":
    main()
