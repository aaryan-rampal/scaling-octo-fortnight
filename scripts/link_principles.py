"""Rung ④ live runner -- MERGE near-duplicate principles then LINK related ones.

Loads ``data/principles.json`` (rung-③ output), boots the Hindsight bank to
recall MemoryCards (needed for ledger reconstruction), runs the MERGE pass
(collapses pairs with cosine >= 0.80), writes ``data/principles.merged.json``,
then runs the LINKING pass (proposes typed edges for pairs in the 0.60-0.80
band) and writes ``data/edges.json``.

**Observability first** (mirrors mint_principles.py):
- Every merge-group is logged before any LLM call.
- Every edge pair, proposal, accept/reject + reason is logged.
- Running counts appear at each step.
- ``--dry-run`` logs group/pair counts but skips all LLM calls and writes.
- ``--limit`` caps the number of pairs sent to the edge-LLM (for smoke).

Note on soft-scope neighborhood: per ``docs/v0-pipeline-contract.md`` rung-4
spec, the edge citation neighborhood is ideally the union of both principles'
``derived_from`` PLUS temporally-near/embedding-similar memories from recall.
This v0 runner uses the simpler union-of-derived_from bound only -- it
trivially satisfies the Edge >=1 guard and all cited ids are groundable. The
richer soft-scope recall pass is deferred.

Full-run command (Doppler injects OPENROUTER_API_KEY; redirect stderr to capture
live progress and save it)::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/link_principles.py \\
        2>&1 | tee /tmp/link_principles.log

Smoke (<=2 pairs, no file writes)::

    doppler run --project berkeley-hackathon --config dev -- \\
        env PYTHONPATH=src .venv/bin/python scripts/link_principles.py \\
        --limit 2 --dry-run 2>&1 | tee /tmp/link_smoke.log
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import sentry_sdk
from loguru import logger

from core.logging import configure_logging
from core.principle import Edge, Principle
from observability.sentry import init_sentry
from pipeline.link import LLMEdgeProposer, run_linking, run_merge
from pipeline.mint import MemoryCard
from pipeline.propose import PgVectorReader, QwenEmbedder, recall_to_cards
from runtime.hindsight import embedded_hindsight

BANK = "slice-7d"
RECALL_QUERY = "personal values, habits, relationships, emotions, recurring patterns"
INPUT_PATH = Path("data/principles.json")
MERGED_PATH = Path("data/principles.merged.json")
EDGES_PATH = Path("data/edges.json")


def _load_principles(path: Path) -> list[dict]:
    """Load and return the rung-③ principles JSON array.

    Args:
        path: Path to principles.json.

    Returns:
        List of principle dicts.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- run scripts/mint_principles.py first to produce rung-③ output."
        )
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array; got {type(data)}")
    return data


def _dict_to_principle(d: dict) -> Principle:
    """Convert a principle dict (from JSON) to a Principle dataclass.

    Args:
        d: Dict with keys id/text/confidence/derived_from.

    Returns:
        A Principle instance.
    """
    return Principle(
        principle_id=d["id"],
        text=d["text"],
        confidence=float(d["confidence"]),
        derived_from=list(d["derived_from"]),
    )


def _build_cards_by_id(cards: list[MemoryCard]) -> dict[str, MemoryCard]:
    """Index MemoryCards by memory_id for O(1) lookup.

    Args:
        cards: The recalled MemoryCards.

    Returns:
        Dict of memory_id -> MemoryCard.
    """
    return {c.memory_id: c for c in cards}


def _principle_to_dict(p: Principle) -> dict:
    """Serialize a Principle to a JSON-compatible dict.

    Args:
        p: The Principle to serialize.

    Returns:
        Dict with keys id/text/confidence/derived_from.
    """
    return {
        "id": p.principle_id,
        "text": p.text,
        "confidence": p.confidence,
        "derived_from": p.derived_from,
    }


def _edge_to_dict(e: Edge) -> dict:
    """Serialize an Edge to a JSON-compatible dict.

    Args:
        e: The Edge to serialize.

    Returns:
        Dict with keys src/dst/relation/derived_from.
    """
    return {
        "src": e.src,
        "dst": e.dst,
        "relation": e.relation,
        "derived_from": e.derived_from,
    }


def main() -> None:
    """Load principles, recall cards for ledger rebuilding, merge, then link."""
    configure_logging()
    init_sentry(component="link")

    ap = argparse.ArgumentParser(
        description="Rung ④: merge near-duplicate principles then link related ones."
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Max edge-link pairs to send to the LLM (0 = all). Use 2 for a smoke.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Log merge-group + pair counts but skip LLM calls and output writes. Free.",
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
            "LIVE PAID RUN: embedding + LLM calls will be made. "
            "Use --dry-run to inspect merge-group/pair counts first."
        )

    # -----------------------------------------------------------------------
    # Load rung-③ principles
    # -----------------------------------------------------------------------
    raw_principles = _load_principles(INPUT_PATH)
    logger.info("loaded {} principles from {}", len(raw_principles), INPUT_PATH)

    principles = [_dict_to_principle(d) for d in raw_principles]

    # -----------------------------------------------------------------------
    # Recall MemoryCards from Hindsight (needed to rebuild ledgers after merge)
    # -----------------------------------------------------------------------
    logger.info("booting bank {} to recall MemoryCards...", args.bank)
    with embedded_hindsight() as client, PgVectorReader() as pg_reader:
        cards = recall_to_cards(client, RECALL_QUERY, args.bank, pg_reader=pg_reader)

    with_emb = sum(1 for c in cards if c.embedding is not None)
    logger.info("recalled {} cards ({} with embeddings)", len(cards), with_emb)

    if not cards:
        logger.error("no cards recalled -- is the bank populated? Aborting.")
        return

    cards_by_id = _build_cards_by_id(cards)

    # -----------------------------------------------------------------------
    # MERGE pass
    # -----------------------------------------------------------------------
    embedder = QwenEmbedder()

    if args.dry_run:
        logger.info("[dry-run] would embed {} principles for merge pass", len(principles))
        n = len(principles)
        max_pairs = n * (n - 1) // 2
        logger.info("[dry-run] up to {} linking pairs after merge", max_pairs)
        logger.info("[dry-run] skipping all LLM calls -- dry-run complete.")
        return

    t0 = time.perf_counter()
    merged_principles = run_merge(principles, embedder, cards_by_id)
    elapsed = time.perf_counter() - t0
    logger.info(
        "merge complete: {} -> {} principles in {:.1f}s",
        len(principles),
        len(merged_principles),
        elapsed,
    )
    MERGED_PATH.parent.mkdir(parents=True, exist_ok=True)
    MERGED_PATH.write_text(json.dumps([_principle_to_dict(p) for p in merged_principles], indent=2))
    logger.info("wrote {} merged principles -> {}", len(merged_principles), MERGED_PATH)

    # -----------------------------------------------------------------------
    # LINKING pass
    # -----------------------------------------------------------------------
    proposer = LLMEdgeProposer()
    t0 = time.perf_counter()
    # One transaction spans the linking pass so every per-pair gen_ai.chat edge
    # span nests under it as a single trace in Sentry's AI Agents view.
    with sentry_sdk.start_transaction(op="link", name="link_principles"):
        edges = run_linking(
            merged_principles,
            embedder,
            proposer,
            limit=args.limit,
        )
    elapsed = time.perf_counter() - t0
    logger.info(
        "linking complete: {} edges from {} principles in {:.1f}s",
        len(edges),
        len(merged_principles),
        elapsed,
    )

    EDGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDGES_PATH.write_text(json.dumps([_edge_to_dict(e) for e in edges], indent=2))
    logger.info("wrote {} edges -> {}", len(edges), EDGES_PATH)

    # Final tally
    rel_counts: dict[str, int] = {}
    for e in edges:
        rel_counts[e.relation] = rel_counts.get(e.relation, 0) + 1
    logger.info("edge relation breakdown: {}", rel_counts)


if __name__ == "__main__":
    main()
