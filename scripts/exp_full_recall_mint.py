"""EXPERIMENT: mint from ALL pg0 memories vs the capped recall() path.

The live mint recalls memories via Hindsight ``recall(max_tokens=6000,
types=["experience","world"])`` — a semantic-search slice that returns only
~100 of pg0's ~1700 memories. This script bypasses that: it pulls EVERY memory
(id + text + embedding) straight from pg0, clusters them with the same
``cluster_memories``, mints with the same ``mint_cluster``, and reports how many
principles that yields vs the live ``data/principles.json`` baseline.

STRICTLY read-only on durable state:
- pg0: SELECT only (no writes).
- recall.db: not touched.
- All output goes to ``/tmp/exp_full_recall/``.

Run AFTER the live link finishes (so pg0 isn't contended)::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/exp_full_recall_mint.py \\
        --threshold 0.78
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import psycopg2
from loguru import logger

from core.logging import configure_logging
from pipeline.mint import (
    MemoryCard,
    build_ledger,
    cluster_memories,
    compute_confidence,
    mint_cluster,
)
from pipeline.propose import LLMProposer, QwenEmbedder, _parse_raw_vector
from runtime.hindsight import embedded_hindsight

PG_DSN = "postgresql://hindsight:hindsight@127.0.0.1:5432/hindsight"
BANK = "slice-7d"
OUT_DIR = Path("/tmp/exp_full_recall")
BASELINE = Path("data/principles.json")


def _pull_all_memories(bank_id: str) -> list[MemoryCard]:
    """Read every memory (id, text, source, embedding) for a bank from pg0.

    Read-only: a single SELECT, connection closed immediately. The source is
    derived from the ``tags`` array the same way dump_bank does.

    Args:
        bank_id: The Hindsight bank to pull.

    Returns:
        One MemoryCard per memory_unit, embeddings joined in.
    """
    conn = psycopg2.connect(PG_DSN, connect_timeout=5)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 30000")
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
    with_emb = sum(1 for c in cards if c.embedding is not None)
    logger.info("with embeddings: {}/{}", with_emb, len(cards))
    return [c for c in cards if c.embedding is not None]


def _mint_all(cards: list[MemoryCard], threshold: float) -> list[dict]:
    """Cluster all cards and mint principles, mirroring the live mint loop."""
    proposer = LLMProposer()
    embedder = QwenEmbedder()
    clusters = cluster_memories(cards, threshold=threshold)
    logger.info("clustered {} cards into {} clusters @ {}", len(cards), len(clusters), threshold)

    principles: list[dict] = []
    for idx, cluster in enumerate(clusters, 1):
        t0 = time.perf_counter()
        try:
            candidates = mint_cluster(cluster, proposer, embedder.embed)
        except Exception as exc:
            logger.error("cluster {} failed: {}: {}", idx, type(exc).__name__, exc)
            continue
        for cand in candidates:
            ledger = build_ledger(cand.cited)
            principles.append(
                {
                    "text": cand.text,
                    "confidence": compute_confidence(ledger),
                    "n_cited": len(cand.cited),
                }
            )
        logger.info(
            "[{}/{}] size={} -> {} principle(s) ({:.1f}s, total {})",
            idx, len(clusters), len(cluster), len(candidates),
            time.perf_counter() - t0, len(principles),
        )
    return principles


def _report(principles: list[dict], threshold: float) -> None:
    """Write results to /tmp and print the diff vs the live baseline."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"principles_full_t{threshold}.json"
    out.write_text(json.dumps(principles, indent=2, ensure_ascii=False), encoding="utf-8")

    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else []
    logger.info("=" * 60)
    logger.info("BASELINE (capped recall):  {} principles", len(baseline))
    logger.info("EXPERIMENT (all of pg0):   {} principles", len(principles))
    logger.info("delta: {:+d}", len(principles) - len(baseline))
    logger.info("wrote {} -> {}", len(principles), out)
    logger.info("=" * 60)
    for p in sorted(principles, key=lambda x: -x["confidence"]):
        logger.info("  [{:.2f}] ({}c) {}", p["confidence"], p["n_cited"], p["text"][:90])


def main() -> None:
    """Pull all pg0 memories, mint, and diff against the live baseline."""
    configure_logging()
    ap = argparse.ArgumentParser(description="Experiment: mint from all pg0 memories.")
    ap.add_argument("--threshold", type=float, default=0.78, help="Cluster cosine threshold.")
    ap.add_argument("--bank", default=BANK)
    args = ap.parse_args()

    # pg0 is embedded — it only exists while a Hindsight process runs. Boot our
    # own so the SELECT has a live server (and we own its lifecycle).
    logger.info("booting embedded Hindsight (starts pg0)...")
    with embedded_hindsight():
        cards = _pull_all_memories(args.bank)
    if not cards:
        logger.error("no embedded memories pulled — is the bank populated?")
        return
    principles = _mint_all(cards, args.threshold)
    _report(principles, args.threshold)


if __name__ == "__main__":
    main()
