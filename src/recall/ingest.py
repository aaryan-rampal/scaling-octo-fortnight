"""Backwards-compatible shim for iMessage ingest.

The real implementation now lives in :mod:`adaptors.imessage`, which follows the
adapter/model pattern (raw ``chat.db`` rows -> :class:`~models.imessage.IMessageRecord`
-> canonical :class:`~recall.schema.Event`). This module re-exports that public
surface so existing importers — the ``recall`` CLI and ``tests/test_ingest.py`` —
keep working unchanged. Prefer importing from :mod:`adaptors.imessage` in new code.
"""

from __future__ import annotations

from adaptors.imessage import (
    APPLE_EPOCH_OFFSET,
    DEFAULT_DB_PATH,
    DEFAULT_OUTPUT,
    apple_ns_to_utc,
    connect_readonly,
    decode_attributed_body,
    ingest,
    main,
    read_records,
    records_to_events,
    top_threads,
)

__all__ = [
    "APPLE_EPOCH_OFFSET",
    "DEFAULT_DB_PATH",
    "DEFAULT_OUTPUT",
    "apple_ns_to_utc",
    "connect_readonly",
    "decode_attributed_body",
    "ingest",
    "main",
    "read_records",
    "records_to_events",
    "top_threads",
]


if __name__ == "__main__":
    main()
