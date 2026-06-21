"""Rung ③ live runner — cluster recalled memories and mint principles.

Boots the ``slice-7d`` bank, recalls all memories, clusters them at threshold
0.78, and runs the LLM proposer over each cluster. Emits live, flushed progress
to **stderr** via loguru (one line per cluster, per proposal, accept/reject reason,
running count, and final tally). Writes accepted principles to
``data/principles.json``.

**Observability first**: progress lines appear before any paid call. The first
log line after boot shows card/cluster counts; only then does LLM spend begin.

Progress shape (stderr)::

    2026-06-21 ... | INFO | recalled 245 cards (230 with embeddings)
    2026-06-21 ... | INFO | clustered into 18 clusters at threshold=0.78
    2026-06-21 ... | INFO | [1/18] cluster size=12
    2026-06-21 ... | INFO |   proposal: "You value deep 1:1 time over group events"
    2026-06-21 ... | INFO |   -> accepted  (principles so far: 1)
    2026-06-21 ... | INFO | [2/18] cluster size=3
    2026-06-21 ... | INFO |   proposal: "You stay up late"
    2026-06-21 ... | INFO |   -> rejected (citation-fail: 1 verified < 2 required)
    ...
    2026-06-21 ... | INFO | done: 8 principles from 18 clusters -> data/principles.json

Full-mint command (Doppler injects OPENROUTER_API_KEY; redirect stderr to capture
live progress and save it)::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/mint_principles.py \\
        2>&1 | tee /tmp/mint_principles.log

Smoke (2 clusters, no JSON output)::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/mint_principles.py \\
        --limit-clusters 2 --dry-run 2>&1 | tee /tmp/mint_smoke.log
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from loguru import logger

from core.logging import configure_logging
from pipeline.mint import (
    _principle_id,
    build_ledger,
    cluster_memories,
    compute_confidence,
    mint_cluster,
)
from pipeline.propose import LLMProposer, PgVectorReader, QwenEmbedder, recall_to_cards
from runtime.hindsight import embedded_hindsight

BANK = "slice-7d"
CLUSTER_THRESHOLD = 0.78
RECALL_QUERY = "personal values, habits, relationships, emotions, recurring patterns"
OUTPUT_PATH = Path("data/principles.json")


def _run_with_observability(
    cards: list,
    proposer: LLMProposer,
    embedder: QwenEmbedder,
    *,
    limit_clusters: int,
    dry_run: bool,
) -> list[dict]:
    """Cluster cards and run per-cluster minting with live log lines.

    Logs every cluster header, every proposal, and each accept/reject with
    reason before writing anything. Returns serialisable principle dicts.

    Args:
        cards: The recalled MemoryCards (with embeddings).
        proposer: Live LLM proposer.
        embedder: Live principle embedder.
        limit_clusters: Cap on clusters to process (0 = all).
        dry_run: When True, skip writing output file and LLM calls after logging
            cluster headers (useful for verifying card/cluster counts cheaply).

    Returns:
        List of principle dicts (id, text, confidence, derived_from).
    """
    clusters = cluster_memories(cards, threshold=CLUSTER_THRESHOLD)
    logger.info("clustered into {} clusters at threshold={}", len(clusters), CLUSTER_THRESHOLD)

    if limit_clusters:
        clusters = clusters[:limit_clusters]
        logger.info("limiting to first {} clusters (--limit-clusters)", len(clusters))

    principles: list[dict] = []
    total = len(clusters)

    for idx, cluster in enumerate(clusters, 1):
        t0 = time.perf_counter()
        logger.info("[{}/{}] cluster size={}", idx, total, len(cluster))

        if dry_run:
            logger.info("  [dry-run] skipping LLM call")
            continue

        try:
            candidates = mint_cluster(cluster, proposer, embedder.embed)
        except Exception as exc:
            logger.error(
                "  cluster {} FAILED ({:.1f}s): {}: {}",
                idx,
                time.perf_counter() - t0,
                type(exc).__name__,
                exc,
            )
            continue

        if not candidates:
            logger.info("  -> no proposals survived (principles so far: {})", len(principles))
            continue

        for cand in candidates:
            logger.info('  proposal: "{}"', cand.text)
            ledger = build_ledger(cand.cited)
            principle = {
                "id": _principle_id(cand.text, cand.cited),
                "text": cand.text,
                "confidence": compute_confidence(ledger),
                "derived_from": [m.memory_id for m in cand.cited],
            }
            principles.append(principle)
            logger.info(
                "  -> accepted (confidence={:.2f}, principles so far: {})",
                principle["confidence"],
                len(principles),
            )

        elapsed = time.perf_counter() - t0
        logger.info("  [cluster done in {:.1f}s | running total: {}]", elapsed, len(principles))

    return principles


def main() -> None:
    """Recall, cluster, propose, and write principles with live observability."""
    configure_logging()

    ap = argparse.ArgumentParser(description="Mint principles from the slice-7d bank.")
    ap.add_argument(
        "--limit-clusters",
        type=int,
        default=0,
        metavar="N",
        help="Process only the first N clusters (0 = all). Use 2 for a cheap smoke.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Log card + cluster counts but skip LLM calls and output. Free.",
    )
    ap.add_argument(
        "--bank",
        default=BANK,
        help=f"Hindsight bank id (default: {BANK}).",
    )
    args = ap.parse_args()

    paid = not args.dry_run
    if paid:
        logger.warning(
            "LIVE PAID RUN: LLM + embedding calls will be made. "
            "Use --dry-run to inspect counts first."
        )

    with embedded_hindsight() as client:
        logger.info("bank booted: {}", args.bank)
        with PgVectorReader() as pg_reader:
            cards = recall_to_cards(client, RECALL_QUERY, args.bank, pg_reader=pg_reader)

    with_emb = sum(1 for c in cards if c.embedding is not None)
    logger.info("recalled {} cards ({} with embeddings)", len(cards), with_emb)

    if not cards:
        logger.error("no cards recalled — is the bank populated? Aborting.")
        return

    proposer = LLMProposer()
    embedder = QwenEmbedder()

    principles = _run_with_observability(
        cards,
        proposer,
        embedder,
        limit_clusters=args.limit_clusters,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        logger.info("dry-run complete — no output written.")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(principles, indent=2))
    logger.info(
        "done: {} principles from {} clusters -> {}",
        len(principles),
        args.limit_clusters or "all",
        OUTPUT_PATH,
    )


if __name__ == "__main__":
    main()
