"""Fallback loader: fold the principle JSON artifacts into recall.db.

The live pipeline writes the principle layer straight into ``recall.db`` (link
stage minting merged principles + edges; dump stage materialising the memory
layer) via :mod:`storage.principle_store`, so a normal run leaves **no JSON at
rest**. This script is the fallback for when those JSON artifacts *do* exist —
e.g. an older run, a hand-edited file, or a debugging round-trip — and you want
to reload them into the DB without re-running the paid stages.

It reads three JSON arrays::

    principles.merged.json (canonical)  ->  derived_from: [memory_id, ...]
    edges.json                          ->  src/dst/relation/derived_from
    bank_snapshot.json                  ->  memory_id -> raw_events[{id,...}]

and writes the same derived tables the live stages do, reusing
:class:`storage.principle_store.PrincipleStore` so the schema, reset semantics,
and insert logic are shared (never duplicated).

Idempotent: the store resets its owned tables in one transaction (it never
touches ``events`` / ``capsules`` / ``media``).

Run::

    PYTHONPATH=src .venv/bin/python scripts/load_principles_db.py

No network, no OpenRouter, no Hindsight. Pure file -> SQLite.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from core.logging import configure_logging
from storage.principle_store import DEFAULT_DB_PATH, PrincipleStore

DEFAULT_PRINCIPLES = Path("data/principles.merged.json")
DEFAULT_EDGES = Path("data/edges.json")
DEFAULT_SNAPSHOT = Path("data/bank_snapshot.json")


def _load_json(path: Path) -> list[dict]:
    """Load a JSON array file, failing loudly if missing or malformed."""
    if not path.exists():
        raise FileNotFoundError(f"required artifact not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array in {path}, got {type(data).__name__}")
    return data


def main() -> None:
    """Load the three JSON artifacts into recall.db's provenance tables."""
    configure_logging()

    ap = argparse.ArgumentParser(description="Load principles/edges/memories into recall.db.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="recall.db path.")
    ap.add_argument("--principles", type=Path, default=DEFAULT_PRINCIPLES)
    ap.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = ap.parse_args()

    principles = _load_json(args.principles)
    edges = _load_json(args.edges)
    snapshot = _load_json(args.snapshot)
    logger.info(
        "loaded artifacts: {} principles, {} edges, {} snapshot memories",
        len(principles),
        len(edges),
        len(snapshot),
    )

    store = PrincipleStore.open(args.db)
    try:
        store.write(principles, edges, snapshot)
    finally:
        store.close()

    logger.info("done -> {}", args.db)


if __name__ == "__main__":
    main()
