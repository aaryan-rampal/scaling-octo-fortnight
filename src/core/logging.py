"""Shared loguru configuration and a per-loop progress helper.

The ingest and enrichment loops run for minutes with no output; when their
stdout/stderr is redirected to a file we need live, unbuffered visibility. This
module centralizes the single loguru sink (so adapters just ``from loguru import
logger`` and emit) and a progress helper that emits one DEBUG line per item plus
an INFO heartbeat every :data:`LOG_EVERY` items.
"""

from __future__ import annotations

import os
import sys

from loguru import logger

#: Emit an INFO heartbeat every this many processed items inside a loop.
LOG_EVERY = 500

#: Env var controlling the sink level; INFO shows heartbeats, DEBUG every item.
LOG_LEVEL_ENV = "RECALL_LOG_LEVEL"


def configure_logging() -> None:
    """Point loguru at a single auto-flushing stderr sink at the env level.

    Replaces loguru's default handler so the level is controlled by
    ``RECALL_LOG_LEVEL`` (default ``INFO``). loguru's stream sink flushes on every
    record, so output stays live even when stderr is redirected to a file.
    """
    level = os.environ.get(LOG_LEVEL_ENV, "INFO").upper()
    logger.remove()
    logger.add(sys.stderr, level=level, enqueue=False)


def log_progress(source: str, index: int, item: str) -> None:
    """Emit a DEBUG line for one item and an INFO heartbeat every ``LOG_EVERY``.

    Args:
        source: Source/phase name shown in every line (e.g. ``"imessage"``).
        index: Zero-based position of the item in the loop.
        item: A short description of the current item for the DEBUG line.
    """
    count = index + 1
    logger.debug("{}: item {} -> {}", source, count, item)
    if count % LOG_EVERY == 0:
        logger.info("{}: {} items processed", source, count)
