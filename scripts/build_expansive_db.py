"""Build a diverse, fully-traceable ``recall_expansive.db`` from pg0 memories.

The normal pipeline mints principles from a capped Hindsight ``recall`` slice
(~111 of ~3458 memories), and naive cluster-first minting over the full pool is
worse: the pool is 92%% claude (3187 claude / 186 imessage / 60 spotify / 25
photos), so embedding clusters are flooded by claude and principles come out
monochrome.

This script instead pulls every pg0 memory, then **stratifies by source** rather
than clustering: claude is down-sampled to a cap, every other source is kept
whole, and each source is sliced into small fixed-size batches that the proposer
mints one at a time. Principles come out labeled by source and balanced across
imessage / spotify / photos / (capped) claude. The full provenance ladder is
materialised into a SEPARATE ``data/recall_expansive.db`` with the same schema as
``recall.db``.

The killed experiment (``scripts/exp_full_recall_mint.py``) saved nothing because
it only reported after all clusters. This script CHECKPOINTS every minted
principle to ``data/expansive_principles.jsonl`` as it goes, so a crash/kill loses
at most the in-flight cluster, and a re-run resumes from the checkpoint without
re-spending OpenRouter.

Ladder materialisation (mirrors the dump-before-link ordering in bootstrap.sh):
1. Copy ``recall.db`` → ``recall_expansive.db`` (gives us the ``events`` raw layer
   read-only; the derived tables get rewritten below).
2. Write the memory layer (``memories`` + ``memory_events``) — same logic as
   ``dump_bank.py`` — so principle_memories has memories to FK against.
3. Write the principle layer (``principles`` + ``principle_memories``) from the
   minted checkpoint. Edges are skipped (principles + full trace is the priority).

STRICTLY read-only on durable state we don't own:
- pg0: SELECT only.
- ``data/recall.db`` and ``data/backups/``: never written (only read/copied once).

Run (LIVE, paid — background it)::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/build_expansive_db.py \\
        > /tmp/expansive_build.log 2>&1 &
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

import psycopg2
from loguru import logger

from core.logging import configure_logging
from core.schema import Event
from pipeline.mint import (
    MemoryCard,
    build_ledger,
    compute_confidence,
    mint_cluster,
)
from pipeline.propose import LLMProposer, QwenEmbedder, _parse_raw_vector
from pipeline.segment import Unit, segment_recent
from runtime.hindsight import embedded_hindsight
from storage.principle_store import PrincipleStore
from storage.store import CapsuleStore

PG_DSN = "postgresql://hindsight:hindsight@127.0.0.1:5432/hindsight"
BANK = "slice-7d"
SOURCE_DB = Path("data/recall.db")
EXPANSIVE_DB = Path("data/recall_expansive.db")
CHECKPOINT = Path("data/expansive_principles.jsonl")


def _principle_id(text: str, cited_ids: list[str]) -> str:
    """Stable id from principle text + sorted cited ids (mirrors mint._principle_id)."""
    import hashlib

    payload = "\x1f".join([text, *sorted(set(cited_ids))])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pull_all_memories(bank_id: str) -> list[MemoryCard]:
    """Read every embedded memory (id, text, source, embedding) for a bank from pg0.

    Args:
        bank_id: The Hindsight bank to pull.

    Returns:
        MemoryCards with embeddings (cards without an embedding are dropped — they
        cannot cluster).
    """
    conn = psycopg2.connect(PG_DSN, connect_timeout=5)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 60000")
            cur.execute(
                "SELECT id::text, text, tags, embedding, occurred_start "
                "FROM memory_units WHERE bank_id = %s",
                (bank_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    known = {"imessage", "spotify", "photos", "claude"}
    cards: list[MemoryCard] = []
    for mid, text, tags, emb, occurred in rows:
        source = next((t for t in (tags or []) if t in known), "")
        cards.append(
            MemoryCard(
                memory_id=mid,
                text=text or "",
                source=source,
                ts=occurred.isoformat() if occurred else "",
                embedding=_parse_raw_vector(emb) if emb is not None else None,
            )
        )
    logger.info("pulled {} memories from pg0 (bank={})", len(cards), bank_id)
    logger.info("by source: {}", dict(Counter(c.source for c in cards)))
    with_emb = [c for c in cards if c.embedding is not None]
    logger.info("with embeddings: {}/{}", len(with_emb), len(cards))
    return with_emb


def _load_checkpoint() -> tuple[list[dict], int]:
    """Load already-minted principles + the last completed cluster index.

    Returns:
        (principle dicts, last_done_cluster_index). ``0`` when no checkpoint.
    """
    if not CHECKPOINT.exists():
        return [], 0
    principles: list[dict] = []
    last_idx = 0
    for line in CHECKPOINT.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        last_idx = max(last_idx, int(rec.get("cluster_idx", 0)))
        if "id" in rec:
            principles.append(rec)
    logger.info(
        "resuming from checkpoint: {} principles, last cluster {}", len(principles), last_idx
    )
    return principles, last_idx


def _append_checkpoint(records: list[dict]) -> None:
    """Append principle/marker records to the JSONL checkpoint (one per line)."""
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _stratified_batches(
    cards: list[MemoryCard], claude_cap: int, batch_size: int, seed: int
) -> list[tuple[str, list[MemoryCard]]]:
    """Group memories by source into small batches — no embedding clustering.

    Clustering-first lets the dominant source (claude, 92% of the pool) flood
    every cluster. Instead we stratify by source: claude is down-sampled to
    ``claude_cap``, every other source is kept whole, and each source is sliced
    into fixed-size batches in timestamp order. The LLM sees one small,
    source-pure batch at a time and must still cite >=2 — so principles come out
    labeled and balanced across sources rather than monochrome.

    Args:
        cards: All embedded memories from pg0.
        claude_cap: Max claude memories to keep (random sample if exceeded).
        batch_size: Memories per batch sent to the proposer.
        seed: RNG seed for the claude down-sample (reproducible).

    Returns:
        List of (source, batch) pairs. Singleton batches (<2 cards) are dropped.
    """
    import random

    by_source: dict[str, list[MemoryCard]] = {}
    for c in cards:
        by_source.setdefault(c.source or "unknown", []).append(c)

    rng = random.Random(seed)
    batches: list[tuple[str, list[MemoryCard]]] = []
    for source in sorted(by_source):
        pool = by_source[source]
        if source == "claude" and len(pool) > claude_cap:
            pool = rng.sample(pool, claude_cap)
            logger.info("claude down-sampled {} -> {}", len(by_source[source]), claude_cap)
        pool = sorted(pool, key=lambda m: m.ts)
        n_batches = 0
        for start in range(0, len(pool), batch_size):
            batch = pool[start : start + batch_size]
            if len(batch) >= 2:
                batches.append((source, batch))
                n_batches += 1
        logger.info("source={} pool={} -> {} batches", source, len(pool), n_batches)
    return batches


def _mint_all(cards: list[MemoryCard], claude_cap: int, batch_size: int, seed: int) -> list[dict]:
    """Mint source-stratified batches (no clustering), checkpointing incrementally.

    Each principle is written to the JSONL checkpoint the moment its batch is
    minted, plus a ``cluster_idx`` progress marker, so a kill loses only the
    in-flight batch and a re-run resumes past completed ones.

    Args:
        cards: All embedded memories from pg0.
        claude_cap: Max claude memories to keep (prunes the dominant source).
        batch_size: Memories per batch.
        seed: RNG seed for the claude down-sample.

    Returns:
        All principle dicts (id/text/confidence/derived_from/source), resumed + new.
    """
    batches = _stratified_batches(cards, claude_cap, batch_size, seed)
    logger.info("stratified {} cards into {} source batches", len(cards), len(batches))

    principles, last_done = _load_checkpoint()
    proposer = LLMProposer()
    embedder = QwenEmbedder()

    for idx, (source, batch) in enumerate(batches, 1):
        if idx <= last_done:
            continue
        t0 = time.perf_counter()
        new_records: list[dict] = []
        try:
            candidates = mint_cluster(batch, proposer, embedder.embed)
        except Exception as exc:
            logger.error("batch {} ({}) failed: {}: {}", idx, source, type(exc).__name__, exc)
            candidates = []
        for cand in candidates:
            ledger = build_ledger(cand.cited)
            derived = [m.memory_id for m in cand.cited]
            rec = {
                "id": _principle_id(cand.text, derived),
                "text": cand.text,
                "confidence": compute_confidence(ledger),
                "derived_from": derived,
                "source": source,
                "cluster_idx": idx,
            }
            new_records.append(rec)
            principles.append(rec)
        # Always write a progress marker, even for empty batches, so resume skips them.
        new_records.append({"cluster_idx": idx, "marker": True})
        _append_checkpoint(new_records)
        logger.info(
            "[{}/{}] {} size={} -> {} principle(s) ({:.1f}s, total {})",
            idx,
            len(batches),
            source,
            len(batch),
            len(candidates),
            time.perf_counter() - t0,
            len([p for p in principles if "id" in p]),
        )
    return [p for p in principles if "id" in p]


def _build_unit_map(window_days: int) -> dict[str, Unit]:
    """Re-segment the expansive store to map document_id -> Unit (dump_bank logic)."""
    window = timedelta(days=window_days) if window_days > 0 else None
    units = segment_recent(db_path=str(EXPANSIVE_DB), window=window)
    logger.info("re-segmented {} units (window={})", len(units), window or "whole-db")
    return {u.unit_id: u for u in units}


def _build_event_map(db_path: Path) -> dict[str, Event]:
    """Load all events from a store and index by event id."""
    store = CapsuleStore(db_path=str(db_path))
    try:
        events = store.list_events()
    finally:
        store.close()
    logger.info("loaded {} events from {}", len(events), db_path)
    return {e.id: e for e in events}


def _project_event(event: Event) -> dict:
    """Project an Event to the 5-field raw_event shape."""
    return {
        "id": event.id,
        "source": event.source,
        "t_utc": event.t_utc.isoformat(),
        "content": event.content,
        "additional_data": dict(event.additional_data),
    }


def _derive_source_and_fact_type(tags: list) -> tuple[str, str]:
    """Derive (source, fact_type) from a memory's tags (dump_bank logic)."""
    source = ""
    fact_type = ""
    known_sources = {"imessage", "spotify", "photos", "claude"}
    for tag in tags or []:
        if tag in known_sources:
            source = tag
        elif tag.startswith("network:"):
            fact_type = tag[len("network:") :]
    return source, fact_type


def _build_memory_records(
    client, bank_id: str, unit_map: dict[str, Unit], event_map: dict[str, Event]
) -> list[dict]:
    """Paginate the bank and build memory-layer records with raw_events provenance.

    Mirrors ``dump_bank._build_snapshot`` but inline (and without the per-source
    hard-fail assertion, which is geared at the live pipeline's source set).

    Args:
        client: A connected Hindsight client.
        bank_id: Bank to read.
        unit_map: document_id -> Unit.
        event_map: event_id -> Event.

    Returns:
        Memory-layer records ready for ``PrincipleStore.write_memory_layer``.
    """
    memories: list[dict] = []
    offset = 0
    total: int | None = None
    while True:
        resp = client.list_memories(bank_id=bank_id, type=None, limit=200, offset=offset)
        if total is None:
            total = int(resp.total)
            logger.info("memory layer: bank total={}", total)
        memories.extend(resp.items)
        offset += len(resp.items)
        if not resp.items or len(memories) >= total:
            break
    logger.info("memory layer: paginated {} memories", len(memories))

    matched = 0
    records: list[dict] = []
    for mem in memories:
        tags = mem.get("tags") or []
        source, fact_type = _derive_source_and_fact_type(tags)
        document_id = mem.get("document_id") or ""
        raw_events: list[dict] = []
        unit = unit_map.get(document_id)
        if unit is not None:
            matched += 1
            raw_events = [
                _project_event(event_map[eid]) for eid in unit.derived_from if eid in event_map
            ]
        records.append(
            {
                "memory_id": mem.get("id", ""),
                "text": mem.get("text", ""),
                "document_id": document_id,
                "source": source,
                "tags": tags,
                "entities": "",
                "occurred_start": mem.get("occurred_start"),
                "fact_type": fact_type,
                "raw_events": raw_events,
            }
        )
    logger.info("memory layer: {}/{} matched a unit", matched, len(records))
    return records


def _materialise_db(principles: list[dict], window_days: int) -> dict[str, int]:
    """Copy recall.db -> recall_expansive.db and write the memory + principle layers.

    Ordering matters (the FK trap): write the memory layer BEFORE the principle
    layer, or principle_memories ends up empty.

    Args:
        principles: Minted principle dicts (id/text/confidence/derived_from).
        window_days: Re-segmentation window (0 = whole DB).

    Returns:
        Combined row counts from both write passes.
    """
    if not SOURCE_DB.exists():
        logger.error("{} not found — cannot seed events layer", SOURCE_DB)
        sys.exit(1)
    logger.info("copying {} -> {}", SOURCE_DB, EXPANSIVE_DB)
    shutil.copy2(SOURCE_DB, EXPANSIVE_DB)

    unit_map = _build_unit_map(window_days)
    event_map = _build_event_map(EXPANSIVE_DB)
    with embedded_hindsight() as client:
        mem_records = _build_memory_records(client, BANK, unit_map, event_map)

    store = PrincipleStore.open(EXPANSIVE_DB)
    try:
        mem_counts = store.write_memory_layer(mem_records)
        p_counts = store.write_principle_layer(principles, [])
    finally:
        store.close()
    return {**mem_counts, **p_counts}


def _verify() -> None:
    """Open recall_expansive.db, run integrity_check, and report trace coverage."""
    import sqlite3

    conn = sqlite3.connect(str(EXPANSIVE_DB))
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        logger.info("integrity_check: {}", ok)

        def n(t: str) -> int:
            return conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]

        n_p = n("principles")
        logger.info(
            "principles={} memories={} memory_events={} principle_memories={} events={}",
            n_p,
            n("memories"),
            n("memory_events"),
            n("principle_memories"),
            n("events"),
        )
        reach = conn.execute(
            "SELECT count(distinct pm.principle_id) FROM principle_memories pm "
            "JOIN memory_events me ON me.memory_id = pm.memory_id"
        ).fetchone()[0]
        logger.info("TRACE: {}/{} principles reach raw events", reach, n_p)
    finally:
        conn.close()


def main() -> None:
    """Pull all pg0 memories, mint every cluster, materialise the expansive DB."""
    configure_logging()
    ap = argparse.ArgumentParser(description="Build full-recall recall_expansive.db.")
    ap.add_argument("--bank", default=BANK)
    ap.add_argument(
        "--claude-cap",
        type=int,
        default=150,
        help="Max claude memories to keep (prunes the 92%%-dominant source). Default 150.",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=12,
        help="Memories per source batch sent to the proposer (no clustering). Default 12.",
    )
    ap.add_argument("--seed", type=int, default=7, help="RNG seed for the claude down-sample.")
    ap.add_argument(
        "--days", type=int, default=0, help="Re-segmentation window (0 = whole DB, matches dump)."
    )
    ap.add_argument(
        "--mint-only", action="store_true", help="Stop after minting (skip DB materialise)."
    )
    ap.add_argument(
        "--materialise-only",
        action="store_true",
        help="Skip minting; build the DB from the existing checkpoint.",
    )
    args = ap.parse_args()

    if args.materialise_only:
        principles, _ = _load_checkpoint()
        principles = [p for p in principles if "id" in p]
        if not principles:
            logger.error("no principles in checkpoint — nothing to materialise")
            sys.exit(1)
    else:
        logger.info("booting embedded Hindsight (starts pg0)...")
        with embedded_hindsight():
            cards = _pull_all_memories(args.bank)
        if not cards:
            logger.error("no embedded memories pulled — is the bank populated?")
            sys.exit(1)
        principles = _mint_all(cards, args.claude_cap, args.batch_size, args.seed)
        logger.info("minting done: {} principles", len(principles))
        if args.mint_only:
            return

    counts = _materialise_db(principles, args.days)
    logger.info("materialised: {}", counts)
    _verify()
    logger.info("DONE -> {}", EXPANSIVE_DB)


if __name__ == "__main__":
    main()
