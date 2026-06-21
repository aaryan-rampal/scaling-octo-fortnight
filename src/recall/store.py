"""SQLite persistence for raw_data — the durable store beside Hindsight.

This is the persistent home for raw data in both paths:

* **active** — user-created :class:`~recall.capsule.Capsule` records and their
  :class:`~recall.capsule.Media` (the binaries live on disk; rows hold refs);
* **passive** — canonical :class:`~recall.schema.Event` rows from sources like
  iMessage / notes / discord, so the raw forms survive independent of Hindsight's
  processed memory.

Hindsight keeps the *synthesized* memory (episodic / semantic / principles); this
store keeps the *ground-truth* rows those are derived from, matching the
flywheel doc's "trace a principle back to its source rows" requirement. It is
deliberately plain ``sqlite3`` — no ORM, no new dependencies — and follows the
POC's file-based-state philosophy: the DB is a single inspectable file under
``data/``.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from recall.capsule import Capsule, Media
from recall.schema import Event


def content_sha(content: str) -> str:
    """Return the provenance hash for an event's content (SHA-256, hex)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

#: Default on-disk location, alongside the JSONL state the POC already writes.
DEFAULT_DB_PATH = Path("data/recall.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS capsules (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    place_name  TEXT NOT NULL,
    lat         REAL,
    lng         REAL
);

CREATE TABLE IF NOT EXISTS media (
    id          TEXT PRIMARY KEY,
    capsule_id  TEXT NOT NULL REFERENCES capsules(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    mime        TEXT NOT NULL,
    byte_size   INTEGER NOT NULL,
    exif_t      TEXT,
    exif_lat    REAL,
    exif_lng    REAL
);

CREATE INDEX IF NOT EXISTS idx_media_capsule ON media(capsule_id);

-- Passive raw_data: canonical events from sources (iMessage / notes / discord).
-- Mirrors recall.schema.Event so passive sources have a persistent home too.
-- content_sha is a provenance hash of the content as ingested: it lets us prove
-- a stored message is byte-identical to what we saw, independent of whether the
-- original source (e.g. chat.db) is later vacuumed, rebuilt, or unavailable.
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    t_utc        TEXT NOT NULL,
    author_role  TEXT NOT NULL,
    content      TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    reply_to     TEXT,
    raw_ref      TEXT NOT NULL,
    source       TEXT NOT NULL,
    content_sha  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_thread ON events(thread_id);
"""


class CapsuleStore:
    """A thin SQLite wrapper for capsules, media, and passive events.

    Each public method opens its own short-lived connection so the store is safe
    to call from FastAPI worker threads (``check_same_thread`` defaults apply per
    connection, and connections never cross threads).
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        """Open (and initialize) the store at ``db_path``.

        Args:
            db_path: Path to the SQLite file. Parent directories are created if
                missing. Use ``":memory:"`` for tests.
        """
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # For an in-memory store the data only lives as long as a connection, so
        # keep one open for the store's lifetime; on-disk stores open per call.
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

    # ---- capsules -------------------------------------------------------

    def add_capsule(self, capsule: Capsule) -> Capsule:
        """Insert a capsule and all of its media in one transaction.

        Args:
            capsule: The capsule to persist; its ``media`` are written too.

        Returns:
            The same capsule, unchanged (returned for call-site convenience).
        """
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO capsules (id, created_at, place_name, lat, lng) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    capsule.id,
                    capsule.created_at.isoformat(),
                    capsule.place_name,
                    capsule.lat,
                    capsule.lng,
                ),
            )
            for m in capsule.media:
                cur.execute(
                    "INSERT INTO media "
                    "(id, capsule_id, kind, file_path, mime, byte_size, "
                    " exif_t, exif_lat, exif_lng) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        m.id,
                        m.capsule_id,
                        m.kind,
                        m.file_path,
                        m.mime,
                        m.byte_size,
                        m.exif_t.isoformat() if m.exif_t else None,
                        m.exif_lat,
                        m.exif_lng,
                    ),
                )
        return capsule

    def get_capsule(self, capsule_id: str) -> Capsule | None:
        """Return one capsule with its media, or ``None`` if not found."""
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM capsules WHERE id = ?", (capsule_id,)
            ).fetchone()
            if row is None:
                return None
            media = self._media_for(cur, capsule_id)
        return self._row_to_capsule(row, media)

    def list_capsules(self) -> list[Capsule]:
        """Return all capsules with their media, newest first."""
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM capsules ORDER BY created_at DESC"
            ).fetchall()
            return [
                self._row_to_capsule(row, self._media_for(cur, row["id"]))
                for row in rows
            ]

    @staticmethod
    def _media_for(cur: sqlite3.Cursor, capsule_id: str) -> list[Media]:
        rows = cur.execute(
            "SELECT * FROM media WHERE capsule_id = ? ORDER BY id", (capsule_id,)
        ).fetchall()
        return [CapsuleStore._row_to_media(r) for r in rows]

    @staticmethod
    def _row_to_media(row: sqlite3.Row) -> Media:
        return Media.from_dict(dict(row))

    @staticmethod
    def _row_to_capsule(row: sqlite3.Row, media: list[Media]) -> Capsule:
        data = dict(row)
        data["media"] = [m.to_dict() for m in media]
        return Capsule.from_dict(data)

    # ---- passive events -------------------------------------------------

    def add_events(self, events: Iterable[Event]) -> int:
        """Upsert canonical events (passive raw_data) into the store.

        Idempotent on ``id`` (``INSERT OR REPLACE``) so re-ingesting a source is
        safe.

        Args:
            events: Canonical events to persist.

        Returns:
            The number of events written.
        """
        count = 0
        with self._cursor() as cur:
            for e in events:
                cur.execute(
                    "INSERT OR REPLACE INTO events "
                    "(id, t_utc, author_role, content, thread_id, reply_to, "
                    " raw_ref, source, content_sha) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        e.id,
                        e.t_utc.isoformat(),
                        e.author_role,
                        e.content,
                        e.thread_id,
                        e.reply_to,
                        e.raw_ref,
                        e.source,
                        content_sha(e.content),
                    ),
                )
                count += 1
        return count

    def list_events(self, source: str | None = None) -> list[Event]:
        """Return stored events, optionally filtered by ``source``.

        The provenance ``content_sha`` column is not part of
        :class:`~recall.schema.Event`, so it is dropped on the way out; use
        :meth:`verify_event` to check it.
        """
        with self._cursor() as cur:
            if source is None:
                rows = cur.execute("SELECT * FROM events ORDER BY t_utc").fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM events WHERE source = ? ORDER BY t_utc",
                    (source,),
                ).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        data = {k: row[k] for k in row.keys() if k != "content_sha"}  # noqa: SIM118
        return Event.from_dict(data)

    def verify_event(self, event_id: str) -> bool | None:
        """Check a stored event's content against its provenance hash.

        Returns ``True`` if the stored content still matches the hash recorded at
        ingest, ``False`` if it has been tampered with, or ``None`` if no event
        with ``event_id`` exists. This is the evidence guarantee: a finding can be
        traced to a message whose integrity we can prove independent of the
        original source.
        """
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT content, content_sha FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return content_sha(row["content"]) == row["content_sha"]

    def close(self) -> None:
        """Close the shared connection, if any (no-op for on-disk stores)."""
        if self._shared is not None:
            self._shared.close()
            self._shared = None
