"""Extract the real provenance graph from recall.db into one JSON for the demo viz.

Bakes everything the self-contained HTML needs to animate and to highlight a
principle's full trace on click — principles, edges, the linked memories each
principle was minted from, and the raw-event snippets those memories fold in —
plus a sample of ALL memories for the "show the full constellation" toggle.

Read-only on recall.db. Writes ``poc_demo/web_viz/demo_data.json`` (override with
``--out``). 2D positions: this mock uses a deterministic layout grouped by
principle; the real build will swap in UMAP coordinates from pg0 embeddings.

Run::

    .venv/bin/python scripts/build_demo_data.py
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from pathlib import Path

DEFAULT_DB = Path("data/recall_expansive.db")
DEFAULT_OUT = Path("backend_viz/public/demo_data.json")
ALL_SAMPLE = 1200  # cap on the "show all memories" constellation for browser perf

#: Observability snapshot for the viz badge. Pulled from Sentry (org amazon-0r,
#: project python) via the gen_ai spans of the Jun-21 pipeline run; the slowest
#: real LLM call in that run. Static snapshot — refresh from Sentry if rerun.
OBSERVABILITY = {
    "slowest_call_ms": 15107,
    "model": "google/gemini-3.5-flash",
    "input_tokens": 1328,
    "output_tokens": 3475,
    "trace_url": "https://amazon-0r.sentry.io/explore/traces/trace/495b45ea24994d91af42ab531f13fa3e",
    # The real debugging story: Sentry surfaced a bottleneck, we fixed it.
    # Steps are the whole loop (Mermaid-style); code is the specific fix.
    "story": {
        "title": "How Sentry found the bottleneck",
        "steps": [
            {"label": "pipeline run", "detail": "90-day fresh build emits gen_ai spans"},
            {"label": "Sentry", "detail": "spans + timings land in the AI dashboard"},
            {"label": "found it", "detail": "Spotify vibe calls serial, ~3.5s each, ~20 in 70s"},
            {"label": "diagnosis", "detail": "300-500 uncached artists = 20-30 min crawl"},
            {"label": "fix", "detail": "fan cache-misses across 8 workers + span each call"},
            {"label": "verified", "detail": "parallel batches; vibe/vision spend now in Sentry"},
        ],
        "code_before": (
            "for artist in artists:\n"
            "    if artist not in cache:\n"
            "        # blocking OpenRouter call, ~3.5s each\n"
            "        cache[artist] = fetch_artist_vibe(artist)\n"
            "    out[artist] = cache[artist]"
        ),
        "code_after": (
            "with ThreadPoolExecutor(max_workers=8) as pool:\n"
            "    futures = {pool.submit(_enrich_one, a): a for a in misses}\n"
            "    for future in as_completed(futures):\n"
            "        with gen_ai_span(operation='chat', model=VIBE_MODEL):\n"
            "            cache[futures[future]] = future.result()"
        ),
        "commit": "26394b0 feat(adapters): parallelize vibe/vision calls + Sentry gen_ai spans",
    },
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _principles(c: sqlite3.Connection) -> list[dict]:
    """Principles with their minted memory ids and a raw-event count."""
    out = []
    rows = c.execute(
        "select id, text, confidence from principles order by confidence desc"
    ).fetchall()
    for r in rows:
        mem_ids = [
            row["memory_id"]
            for row in c.execute(
                "select memory_id from principle_memories where principle_id = ?", (r["id"],)
            )
        ]
        raw_count = c.execute(
            "select count(distinct me.event_id) from principle_memories pm "
            "join memory_events me on me.memory_id = pm.memory_id where pm.principle_id = ?",
            (r["id"],),
        ).fetchone()[0]
        out.append(
            {
                "id": r["id"],
                "text": r["text"],
                "confidence": r["confidence"],
                "memory_ids": mem_ids,
                "raw_count": raw_count,
            }
        )
    return out


def _edges(c: sqlite3.Connection) -> list[dict]:
    return [
        {"src": r["src_principle_id"], "dst": r["dst_principle_id"], "relation": r["relation"]}
        for r in c.execute("select src_principle_id, dst_principle_id, relation from edges")
    ]


def _linked_memories(c: sqlite3.Connection) -> list[dict]:
    """The memories that connect to >=1 principle, with raw-event snippets."""
    ids = [r["memory_id"] for r in c.execute("select distinct memory_id from principle_memories")]
    out = []
    for mid in ids:
        m = c.execute(
            "select memory_id, text, source, fact_type from memories where memory_id = ?", (mid,)
        ).fetchone()
        if m is None:
            continue
        raws = [
            {"source": e["source"], "content": (e["content"] or "")[:140]}
            for e in c.execute(
                "select e.source, e.content from memory_events me "
                "join events e on e.id = me.event_id "
                "where me.memory_id = ? and e.content is not null limit 8",
                (mid,),
            )
        ]
        raw_total = c.execute(
            "select count(*) from memory_events where memory_id = ?", (mid,)
        ).fetchone()[0]
        out.append(
            {
                "id": m["memory_id"],
                "text": m["text"],
                "source": m["source"],
                "fact_type": m["fact_type"],
                "type": _mem_type(m["fact_type"]),
                "raw_sample": raws,
                "raw_total": raw_total,
            }
        )
    return out


#: Hindsight network -> the user-facing memory-type label we render.
_TYPE_LABEL = {"experience": "episodic", "world": "semantic", "entity": "entity"}


def _mem_type(fact_type: str | None) -> str:
    """Map a memory's fact_type to its episodic/semantic/entity label."""
    return _TYPE_LABEL.get(fact_type or "", "episodic")


def _all_memories_sample(c: sqlite3.Connection, limit: int) -> list[dict]:
    """A sample of every memory (id, source, type, short text) for hover + toggle."""
    return [
        {
            "id": r["memory_id"],
            "source": r["source"],
            "type": _mem_type(r["fact_type"]),
            "text": (r["text"] or "")[:120],
        }
        for r in c.execute(
            "select memory_id, source, fact_type, text from memories limit ?", (limit,)
        )
    ]


def _layout(principles: list[dict], linked: list[dict]) -> None:
    """Assign deterministic 2D positions: memories orbit their principle.

    Mutates principles/linked in place, adding ``x``/``y`` in [0,1]. The real
    build replaces this with UMAP coordinates over pg0 embeddings; this mock
    just needs a stable, legible layout to judge density and the click-trace.
    """
    n = len(principles)
    mem_by_id = {m["id"]: m for m in linked}
    for pi, p in enumerate(principles):
        # principles on a circle
        ang = 2 * math.pi * pi / max(n, 1)
        px, py = 0.5 + 0.34 * math.cos(ang), 0.5 + 0.34 * math.sin(ang)
        p["x"], p["y"] = px, py
        for mi, mid in enumerate(p["memory_ids"]):
            m = mem_by_id.get(mid)
            if m is None or "x" in m:
                continue
            ma = ang + (mi - len(p["memory_ids"]) / 2) * 0.18
            m["x"] = px + 0.12 * math.cos(ma)
            m["y"] = py + 0.12 * math.sin(ma)
    for m in linked:
        m.setdefault("x", 0.5)
        m.setdefault("y", 0.5)


def _raw_stream(c: sqlite3.Connection, n: int = 18, windows: int = 3) -> list[dict]:
    """Sample real raw messages and assign each to a window bin for the viz.

    The windowing animation shows many messages flying in, then regrouping into
    a few temporal windows. We pre-assign each sampled message a window index
    (round-robin by recency proxy) and its source, so the front end just animates
    positions — no logic on the client.

    Args:
        c: Read-only recall.db connection.
        n: How many messages to sample.
        windows: Number of window bins to spread them across.

    Returns:
        ``[{source, content, window}]`` — one per sampled message.
    """
    rows = c.execute(
        "select source, content from events "
        "where content is not null and length(content) > 15 "
        "order by t_utc limit ?",
        (n,),
    ).fetchall()
    return [
        {"source": r["source"], "content": (r["content"] or "")[:60], "window": idx % windows}
        for idx, r in enumerate(rows)
    ]


def _trace_example(c: sqlite3.Connection, principles: list[dict], clusters: list[dict]) -> dict:
    """Bake ONE concrete end-to-end trace for the Mermaid-style forward pass.

    Picks the merge-survivor principle (so the merge step is real) and one of its
    memories, then materialises the full chain the demo narrates step by step:
    raw rows -> events table -> Hindsight -> the memory store it landed in
    (episodic/semantic) + the actual fact -> its cluster -> the principle.

    Returns a dict the viz reads stage by stage; empty dict if nothing traces.
    """
    merges = _forward_steps(principles, _edges(c)).get("merges") or []
    survivor_id = merges[0]["survivor"]["id"] if merges else None
    fallback = principles[0] if principles else None
    p = next((x for x in principles if x["id"] == survivor_id), fallback)
    if p is None:
        return {}

    mem_rows = [
        c.execute(
            "select memory_id, text, source, fact_type from memories where memory_id = ?", (mid,)
        ).fetchone()
        for mid in p["memory_ids"]
    ]
    # Prefer an imessage-sourced memory (cleanest raw rows for the demo).
    mem = next((m for m in mem_rows if m and m["source"] == "imessage"), None) or next(
        (m for m in mem_rows if m), None
    )
    if mem is None:
        return {}

    raws = [
        {"source": r["source"], "content": (r["content"] or "")[:160]}
        for r in c.execute(
            "select e.source, e.content from memory_events me "
            "join events e on e.id = me.event_id "
            "where me.memory_id = ? and e.content is not null limit 3",
            (mem["memory_id"],),
        )
    ]
    store = "semantic" if mem["fact_type"] == "world" else "episodic"
    cluster = next((cl for cl in clusters if cl["principle_id"] == p["id"]), None)
    return {
        "raw_rows": raws,
        "raw_stream": _raw_stream(c),
        "memory": {"text": mem["text"], "source": mem["source"], "store": store},
        "cluster_id": p["id"],
        "cluster_point": (
            {"x": cluster["cx"], "y": cluster["cy"]} if cluster else {"x": 0.5, "y": 0.5}
        ),
        "principle": {"id": p["id"], "text": p["text"]},
        "merge": merges[0] if merges else None,
    }


def _mock_clusters(principles: list[dict], linked: list[dict]) -> list[dict]:
    """Mock cluster blobs for the forward-pass viz — one cluster per principle.

    Each cluster gets a stable centroid on a grid-ish ring and its member memory
    dots scattered in a deterministic random cloud around it (seeded per cluster,
    so positions never jitter between builds). Shape matches what the real pg0
    embedding dump will emit (centroid + member points in [0,1]^2), so swapping
    in true UMAP coordinates is a drop-in replacement — only this function changes.

    Args:
        principles: Canonical principles (each with id, text, memory_ids).
        linked: The linked memories (for source/type labels on dots).

    Returns:
        One dict per cluster: ``{principle_id, label, cx, cy, members:[{x,y,source}]}``.
    """
    mem_by_id = {m["id"]: m for m in linked}
    n = len(principles)
    clusters: list[dict] = []
    for i, p in enumerate(principles):
        rng = random.Random(p["id"])  # stable per principle
        ang = 2 * math.pi * i / max(n, 1)
        # keep centroids inside [0.16, 0.84] so blobs never clip the field edge
        radius = 0.26 if i % 2 == 0 else 0.16
        cx = 0.5 + radius * math.cos(ang)
        cy = 0.5 + radius * math.sin(ang)
        members = []
        spread = 0.05
        # real linked memories of this principle
        for mid in p["memory_ids"]:
            members.append(
                {
                    "x": min(1.0, max(0.0, cx + rng.gauss(0, spread))),
                    "y": min(1.0, max(0.0, cy + rng.gauss(0, spread))),
                    "source": (mem_by_id.get(mid, {}) or {}).get("source", "unknown"),
                }
            )
        # pad with background dots so the embedding field looks dense (display-only)
        sources = ["claude", "imessage", "spotify", "photos"]
        for _ in range(14 - len(members)):
            members.append(
                {
                    "x": min(1.0, max(0.0, cx + rng.gauss(0, spread))),
                    "y": min(1.0, max(0.0, cy + rng.gauss(0, spread))),
                    "source": rng.choice(sources),
                }
            )
        clusters.append(
            {
                "principle_id": p["id"],
                "label": p["text"][:48],
                "cx": cx,
                "cy": cy,
                "members": members,
            }
        )
    return clusters


TRACE_PATH = Path("data/link_trace.json")


def _forward_steps(principles: list[dict], edges: list[dict]) -> dict:
    """Build the forward-pass (cluster -> mint -> merge -> link) payload.

    Prefers the REAL ``data/link_trace.json`` written by link_principles.py (its
    captured merge groups + link pairs). When that file is absent or has no
    merges (a run where nothing collapsed), falls back to a representative merge
    derived from the two most textually-similar real principles, so the forward
    animation still has a merge to show. Either way the principles, clusters
    (derived_from), and edges are real; only the *fallback* merge pairing is
    illustrative, and it is flagged as such.

    Args:
        principles: Canonical principles (each with derived_from).
        edges: Real principle->principle edges.

    Returns:
        ``{"merges": [...], "links": [...], "merge_is_illustrative": bool}``.
    """
    if TRACE_PATH.exists():
        trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
        if trace.get("merges"):
            return {
                "merges": trace["merges"],
                "links": trace.get("link_pairs", []),
                "merge_is_illustrative": False,
            }

    # Fallback: pick the two principles whose texts share the most words as a
    # believable "would-merge" example (real near-duplicate, deterministic).
    def _words(t: str) -> set[str]:
        return {w for w in t.lower().split() if len(w) > 3}

    best: tuple[float, dict, dict] | None = None
    for i, a in enumerate(principles):
        for b in principles[i + 1 :]:
            wa, wb = _words(a["text"]), _words(b["text"])
            if not wa or not wb:
                continue
            sim = len(wa & wb) / len(wa | wb)
            if best is None or sim > best[0]:
                best = (sim, a, b)

    merges = []
    if best is not None:
        _, survivor, absorbed = best
        merges = [
            {
                "merged_id": survivor["id"],
                "survivor": {"id": survivor["id"], "text": survivor["text"]},
                "absorbed": [{"id": absorbed["id"], "text": absorbed["text"]}],
            }
        ]
    links = [{"src": e["src"], "dst": e["dst"], "relation": e["relation"]} for e in edges]
    return {"merges": merges, "links": links, "merge_is_illustrative": True}


def main() -> None:
    """Build the demo JSON from recall.db."""
    ap = argparse.ArgumentParser(description="Extract recall.db provenance for the demo viz.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--all-sample", type=int, default=ALL_SAMPLE)
    args = ap.parse_args()

    c = _connect(args.db)
    try:
        principles = _principles(c)
        edges = _edges(c)
        linked = _linked_memories(c)
        all_sample = _all_memories_sample(c, args.all_sample)
        forward = _forward_steps(principles, edges)
        counts = {
            "events": c.execute("select count(*) from events").fetchone()[0],
            "memories": c.execute("select count(*) from memories").fetchone()[0],
            "principles": len(principles),
            "edges": len(edges),
            "linked_memories": len(linked),
        }
        by_source = dict(c.execute("select source, count(*) from events group by source"))
        by_type = {
            _mem_type(r[0]): r[1]
            for r in c.execute("select fact_type, count(*) from memories group by fact_type")
        }
        clusters = _mock_clusters(principles, linked)
        trace_example = _trace_example(c, principles, clusters)
    finally:
        c.close()

    _layout(principles, linked)

    payload = {
        "counts": counts,
        "events_by_source": by_source,
        "memories_by_type": by_type,
        "principles": principles,
        "edges": edges,
        "linked_memories": linked,
        "all_memories_sample": all_sample,
        "forward": forward,
        "clusters": clusters,
        "trace_example": trace_example,
        "observability": OBSERVABILITY,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  {counts}")


if __name__ == "__main__":
    main()
