"""SQLite persistence for photo raw_data — the durable home for the ``photos`` table.

This mirrors the idiom of :mod:`recall.store` (per-call short-lived connections,
``content_sha`` provenance hash, ``INSERT OR REPLACE`` idempotency) but lives in
its own module and owns its own table, so it never collides with the iMessage
events code or the parallel LLM-chat adapter.

Rows reference photo originals on disk by path; **no binary is ever copied**,
keeping the DB small (same philosophy as ``Media.file_path``). The ``content_sha``
column hashes a stable serialization of each record's identifying metadata, giving
the same "prove this row is byte-identical to what we ingested" guarantee the
events table has — even if the source ``Photos.sqlite`` is later rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from models.photo import PhotoRecord

#: Default on-disk location, alongside the rest of the recall store.
DEFAULT_DB_PATH = Path("data/recall.db")

_SCHEMA = """
-- Photo/video raw_data from Apple Photos. Rows reference originals on disk
-- (original_path); binaries are never copied. people is a JSON array of named
-- people only. content_sha is a provenance hash over the identifying metadata.
CREATE TABLE IF NOT EXISTS photos (
    id                TEXT PRIMARY KEY,
    captured_at       TEXT NOT NULL,
    lat               REAL,
    lng               REAL,
    original_filename TEXT NOT NULL,
    original_path     TEXT NOT NULL,
    width             INTEGER NOT NULL,
    height            INTEGER NOT NULL,
    is_favorite       INTEGER NOT NULL,
    is_hidden         INTEGER NOT NULL,
    is_trashed        INTEGER NOT NULL,
    kind              TEXT NOT NULL,
    people            TEXT NOT NULL,
    raw_ref           TEXT NOT NULL,
    content_sha       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_photos_captured ON photos(captured_at);
CREATE INDEX IF NOT EXISTS idx_photos_kind ON photos(kind);
"""


def photo_content_sha(record: PhotoRecord) -> str:
    """Return the provenance hash for a photo record (SHA-256 hex).

    Hashes a deterministic JSON serialization of the record's identifying
    metadata (capture time, path, geo, dims, flags, people, source ref) so a
    stored row can later be proven byte-identical to what was ingested, even if
    the source library is rebuilt.

    Args:
        record: The photo record to hash.

    Returns:
        The hex SHA-256 digest of the canonicalized record.
    """
    payload = json.dumps(
        {
            "id": record.id,
            "captured_at": record.captured_at.isoformat(),
            "lat": record.lat,
            "lng": record.lng,
            "original_filename": record.original_filename,
            "original_path": record.original_path,
            "width": record.width,
            "height": record.height,
            "is_favorite": record.is_favorite,
            "is_hidden": record.is_hidden,
            "is_trashed": record.is_trashed,
            "kind": record.kind,
            "people": record.people,
            "raw_ref": record.raw_ref,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PhotoStore:
    """A thin SQLite wrapper for the ``photos`` table.

    Each public method opens its own short-lived connection (on-disk stores) so
    the store is safe to call from worker threads; an in-memory store keeps one
    connection alive for its lifetime since ``:memory:`` data dies with the
    connection. This matches :class:`recall.store.CapsuleStore`.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        """Open (and initialize) the photo store at ``db_path``.

        Args:
            db_path: Path to the SQLite file. Parent directories are created if
                missing. Use ``":memory:"`` for tests.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared: sqlite3.Connection | None = (
            self._connect() if self.db_path == ":memory:" else None
        )
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Yield a cursor in a transaction, committing on success."""
        conn = self._shared or self._connect()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        finally:
            if self._shared is None:
                conn.close()

    def add_photos(self, photos: Iterable[PhotoRecord]) -> int:
        """Upsert photo records into the store.

        Idempotent on ``id`` (``INSERT OR REPLACE``) so re-ingesting the library
        is safe and never duplicates rows.

        Args:
            photos: Photo records to persist.

        Returns:
            The number of records written.
        """
        count = 0
        with self._cursor() as cur:
            for p in photos:
                cur.execute(
                    "INSERT OR REPLACE INTO photos "
                    "(id, captured_at, lat, lng, original_filename, original_path, "
                    " width, height, is_favorite, is_hidden, is_trashed, kind, "
                    " people, raw_ref, content_sha) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        p.id,
                        p.captured_at.isoformat(),
                        p.lat,
                        p.lng,
                        p.original_filename,
                        p.original_path,
                        p.width,
                        p.height,
                        int(p.is_favorite),
                        int(p.is_hidden),
                        int(p.is_trashed),
                        p.kind,
                        json.dumps(p.people, ensure_ascii=False),
                        p.raw_ref,
                        photo_content_sha(p),
                    ),
                )
                count += 1
        return count

    def list_photos(self) -> list[PhotoRecord]:
        """Return all stored photo records, oldest capture first."""
        with self._cursor() as cur:
            rows = cur.execute("SELECT * FROM photos ORDER BY captured_at").fetchall()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PhotoRecord:
        return PhotoRecord(
            id=row["id"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            lat=row["lat"],
            lng=row["lng"],
            original_filename=row["original_filename"],
            original_path=row["original_path"],
            width=row["width"],
            height=row["height"],
            is_favorite=bool(row["is_favorite"]),
            is_hidden=bool(row["is_hidden"]),
            is_trashed=bool(row["is_trashed"]),
            kind="video" if row["kind"] == "video" else "photo",
            people=json.loads(row["people"]),
            raw_ref=row["raw_ref"],
        )

    def count(self) -> int:
        """Return the number of photo rows currently stored."""
        with self._cursor() as cur:
            return cur.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

    def close(self) -> None:
        """Close the shared connection, if any (no-op for on-disk stores)."""
        if self._shared is not None:
            self._shared.close()
            self._shared = None
