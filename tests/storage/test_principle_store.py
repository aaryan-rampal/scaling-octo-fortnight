"""Tests for the DB-direct principle-layer store (no network, fixtures only)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.schema import Event
from storage.principle_store import PrincipleStore, edge_id
from storage.store import CapsuleStore


def _event(eid: str) -> Event:
    """Build a minimal canonical event for the raw layer."""
    return Event(
        id=eid,
        t_utc=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        author_role="self",
        content=f"content for {eid}",
        thread_id="thread-1",
        reply_to=None,
        raw_ref=f"chat.db#{eid}",
        source="imessage",
    )


def _seed_db(path: Path, event_ids: list[str]) -> None:
    """Create recall.db with the raw events table populated via CapsuleStore."""
    store = CapsuleStore(path)
    store.add_events(_event(e) for e in event_ids)
    store.close()


def _memories(*memory_ids: str, raw_events: dict[str, list[str]] | None = None) -> list[dict]:
    """Build memory records, each linking to the given raw event ids."""
    raw_events = raw_events or {}
    return [
        {
            "memory_id": mid,
            "text": f"memory {mid}",
            "document_id": f"unit-{mid}",
            "source": "imessage",
            "fact_type": "world",
            "entities": "",
            "occurred_start": None,
            "tags": ["imessage"],
            "raw_events": [{"id": e} for e in raw_events.get(mid, [])],
        }
        for mid in memory_ids
    ]


def _principle(pid: str, derived_from: list[str]) -> dict:
    return {"id": pid, "text": f"principle {pid}", "confidence": 0.9, "derived_from": derived_from}


def _edge(src: str, dst: str, derived_from: list[str]) -> dict:
    return {"src": src, "dst": dst, "relation": "supports", "derived_from": derived_from}


def _counts(path: Path) -> dict[str, int]:
    """Return row counts for every derived + raw table."""
    conn = sqlite3.connect(str(path))
    try:
        tables = [
            "events",
            "memories",
            "memory_events",
            "principles",
            "principle_memories",
            "edges",
            "edge_memories",
        ]
        present = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return {
            t: (conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in present else 0)
            for t in tables
        }
    finally:
        conn.close()


def test_open_missing_db_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PrincipleStore.open(tmp_path / "nope.db")


def test_reset_rejects_unowned_table(tmp_path: Path) -> None:
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1"])
    store = PrincipleStore.open(db)
    try:
        with pytest.raises(ValueError, match="does not own"):
            store.reset(["events"])
    finally:
        store.close()


def test_write_full_ladder_and_trace(tmp_path: Path) -> None:
    """A principle resolves down to a raw event via plain joins after a write."""
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1", "e2", "e3"])

    memories = _memories("m1", "m2", raw_events={"m1": ["e1", "e2"], "m2": ["e3"]})
    principles = [_principle("p1", ["m1", "m2"])]
    edges: list[dict] = []

    store = PrincipleStore.open(db)
    try:
        counts = store.write(principles, edges, memories)
    finally:
        store.close()

    assert counts["memories"] == 2
    assert counts["memory_events"] == 3
    assert counts["principles"] == 1
    assert counts["principle_memories"] == 2

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT e.id FROM principles p "
            "JOIN principle_memories pm ON pm.principle_id = p.id "
            "JOIN memory_events me ON me.memory_id = pm.memory_id "
            "JOIN events e ON e.id = me.event_id "
            "WHERE p.id = 'p1' ORDER BY e.id"
        ).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["e1", "e2", "e3"]


def test_reset_leaves_raw_tables_intact(tmp_path: Path) -> None:
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1", "e2"])
    before = _counts(db)

    store = PrincipleStore.open(db)
    try:
        store.write(
            [_principle("p1", ["m1", "m2"])],
            [],
            _memories("m1", "m2", raw_events={"m1": ["e1"], "m2": ["e2"]}),
        )
    finally:
        store.close()

    after = _counts(db)
    assert after["events"] == before["events"] == 2


def test_rerun_shrinks_row_counts(tmp_path: Path) -> None:
    """A 3-principle run followed by a 2-principle run ends with exactly 2."""
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1", "e2", "e3"])
    memories = _memories(
        "m1", "m2", "m3", raw_events={"m1": ["e1"], "m2": ["e2"], "m3": ["e3"]}
    )

    store = PrincipleStore.open(db)
    try:
        store.write(
            [
                _principle("p1", ["m1", "m2"]),
                _principle("p2", ["m2", "m3"]),
                _principle("p3", ["m1", "m3"]),
            ],
            [],
            memories,
        )
    finally:
        store.close()
    assert _counts(db)["principles"] == 3

    store = PrincipleStore.open(db)
    try:
        store.write(
            [_principle("p1", ["m1", "m2"]), _principle("p2", ["m2", "m3"])],
            [],
            memories,
        )
    finally:
        store.close()
    after = _counts(db)
    assert after["principles"] == 2
    assert after["events"] == 3


def test_split_writes_dump_then_link(tmp_path: Path) -> None:
    """Memory layer (dump) then principle layer (link) compose without clobbering."""
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1", "e2"])

    # dump stage: memory layer only
    store = PrincipleStore.open(db)
    try:
        store.write_memory_layer(
            _memories("m1", "m2", raw_events={"m1": ["e1"], "m2": ["e2"]})
        )
    finally:
        store.close()

    # link stage: principle layer only, validated against the memories above
    store = PrincipleStore.open(db)
    try:
        store.write_principle_layer(
            [_principle("p1", ["m1", "m2"]), _principle("p2", ["m1", "m2"])],
            [_edge("p1", "p2", ["m1"])],
        )
    finally:
        store.close()

    after = _counts(db)
    assert after["memories"] == 2
    assert after["memory_events"] == 2
    assert after["principles"] == 2
    assert after["edges"] == 1
    assert after["edge_memories"] == 1


def test_link_rerun_preserves_memory_layer(tmp_path: Path) -> None:
    """Re-running the link stage must not wipe the memory layer dump wrote."""
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1", "e2"])

    store = PrincipleStore.open(db)
    try:
        store.write_memory_layer(
            _memories("m1", "m2", raw_events={"m1": ["e1"], "m2": ["e2"]})
        )
    finally:
        store.close()

    for _ in range(2):
        store = PrincipleStore.open(db)
        try:
            store.write_principle_layer([_principle("p1", ["m1", "m2"])], [])
        finally:
            store.close()

    after = _counts(db)
    assert after["memories"] == 2
    assert after["memory_events"] == 2
    assert after["principles"] == 1


def test_edge_id_is_stable() -> None:
    a = edge_id("p1", "p2", "supports")
    b = edge_id("p1", "p2", "supports")
    c = edge_id("p2", "p1", "supports")
    assert a == b
    assert a != c


def test_dangling_memory_links_are_skipped(tmp_path: Path) -> None:
    """A principle citing an unknown memory_id writes the principle but skips the link."""
    db = tmp_path / "recall.db"
    _seed_db(db, ["e1"])

    store = PrincipleStore.open(db)
    try:
        store.write(
            [_principle("p1", ["m1", "ghost"])],
            [],
            _memories("m1", "m2", raw_events={"m1": ["e1"]}),
        )
    finally:
        store.close()

    after = _counts(db)
    assert after["principles"] == 1
    assert after["principle_memories"] == 1
