"""Read-only adapter: Apple ``Photos.sqlite`` → :class:`PhotoRecord` rows.

The Apple Photos database is treated as strictly read-only. We open it with
SQLite's ``immutable=1`` URI flag, which lets us read past an active WAL without
taking a lock or writing anything back to the user's library. If the immutable
open ever fails (e.g. a future macOS lock), :func:`ingest_photos` falls back to
copying the three sidecar files (``.sqlite``, ``-wal``, ``-shm``) into a temp dir
and reading the *copy* — the originals are never modified, and photo binaries are
never touched.

Only metadata is read. Named people are joined in; anonymous face clusters (rows
with a null ``ZDISPLAYNAME``) are skipped because their cluster ids are
meaningless without a label. Scene classifications are deliberately ignored: they
are internal ML enum ids with no human-readable label table.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from models.photo import PhotoRecord

# Apple's Core Data epoch (2001-01-01 UTC) as seconds past the Unix epoch.
# ``ZASSET.ZDATECREATED`` is stored in seconds since this epoch (mirrors the
# iMessage ingest's APPLE_EPOCH_OFFSET, which uses nanoseconds).
APPLE_EPOCH_OFFSET = 978_307_200

# Missing GPS is stored as this sentinel pair rather than NULL; map it to None.
GPS_SENTINEL = -180.0


def _kind_from_code(code: int) -> Literal["photo", "video"]:
    """Map the ``ZASSET.ZKIND`` enum to a kind label (1 is video, else photo)."""
    return "video" if code == 1 else "photo"


# Pulls one row per asset with its original filename and a comma-joined list of
# *named* people. The CASE inside GROUP_CONCAT emits only non-null ZDISPLAYNAME
# values, so the LEFT JOINs keep faceless assets and assets whose only faces are
# anonymous clusters come back with NULL named_people.
_QUERY = """
SELECT
    a.Z_PK            AS pk,
    a.ZUUID           AS uuid,
    a.ZDATECREATED    AS date_created,
    a.ZLATITUDE       AS lat,
    a.ZLONGITUDE      AS lng,
    a.ZDIRECTORY      AS directory,
    a.ZFILENAME       AS filename,
    a.ZWIDTH          AS width,
    a.ZHEIGHT         AS height,
    a.ZFAVORITE       AS favorite,
    a.ZHIDDEN         AS hidden,
    a.ZTRASHEDSTATE   AS trashed,
    a.ZKIND           AS kind,
    aaa.ZORIGINALFILENAME AS original_filename,
    GROUP_CONCAT(
        CASE WHEN p.ZDISPLAYNAME IS NOT NULL THEN p.ZDISPLAYNAME END
    ) AS named_people
FROM ZASSET a
LEFT JOIN ZADDITIONALASSETATTRIBUTES aaa ON aaa.ZASSET = a.Z_PK
LEFT JOIN ZDETECTEDFACE df ON df.ZASSETFORFACE = a.Z_PK
LEFT JOIN ZPERSON p ON p.Z_PK = df.ZPERSONFORFACE
GROUP BY a.Z_PK
ORDER BY a.Z_PK
"""


def apple_date_to_utc(seconds: float) -> datetime:
    """Convert an Apple Core Data timestamp to a UTC datetime.

    Args:
        seconds: Seconds since the Apple epoch (2001-01-01 UTC), as stored in
            ``ZASSET.ZDATECREATED``.

    Returns:
        A timezone-aware UTC datetime.
    """
    return datetime.fromtimestamp(seconds + APPLE_EPOCH_OFFSET, tz=UTC)


def _coord_or_none(value: float | None) -> float | None:
    """Return a GPS coordinate, mapping the ``-180`` sentinel (and NULL) to None."""
    if value is None or value == GPS_SENTINEL:
        return None
    return value


def _parse_people(named_people: str | None) -> list[str]:
    """Split the comma-joined named-people string into a de-duplicated sorted list.

    Args:
        named_people: ``GROUP_CONCAT`` output of named ``ZDISPLAYNAME`` values, or
            ``None`` when the asset has no named people.

    Returns:
        Sorted unique display names; empty when there are none.
    """
    if not named_people:
        return []
    return sorted({name for name in named_people.split(",") if name})


def _row_to_record(row: sqlite3.Row) -> PhotoRecord:
    """Map one joined query row to a :class:`PhotoRecord`."""
    directory = row["directory"] or ""
    filename = row["filename"] or ""
    return PhotoRecord(
        id=row["uuid"],
        captured_at=apple_date_to_utc(row["date_created"]),
        lat=_coord_or_none(row["lat"]),
        lng=_coord_or_none(row["lng"]),
        original_filename=row["original_filename"] or filename,
        original_path=f"originals/{directory}/{filename}",
        width=row["width"] or 0,
        height=row["height"] or 0,
        is_favorite=bool(row["favorite"]),
        is_hidden=bool(row["hidden"]),
        is_trashed=bool(row["trashed"]),
        kind=_kind_from_code(row["kind"]),
        people=_parse_people(row["named_people"]),
        raw_ref=f"photos.sqlite#{row['pk']}",
    )


@contextmanager
def _open_readonly(db_path: str) -> Iterator[sqlite3.Connection]:
    """Open ``Photos.sqlite`` read-only, falling back to a sidecar copy if locked.

    First tries SQLite's ``immutable=1`` URI mode, which reads past an active WAL
    without locking. If that raises (a locked DB), the three sidecar files are
    copied to a temp directory and the *copy* is opened read-only. The originals
    are never written; photo binaries are never copied.

    Args:
        db_path: Path to the live ``Photos.sqlite``.

    Yields:
        A read-only SQLite connection with ``sqlite3.Row`` row factory.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
        return
    except sqlite3.OperationalError:
        pass

    src = Path(db_path)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / src.name
        for suffix in ("", "-wal", "-shm"):
            sidecar = src.with_name(src.name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, Path(tmp) / sidecar.name)
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def ingest_photos(db_path: str) -> list[PhotoRecord]:
    """Read all assets from a ``Photos.sqlite`` into :class:`PhotoRecord` rows.

    Every asset (photos and videos, including hidden/trashed) is returned so the
    durable store holds the full library; downstream loaders can filter. The DB is
    opened read-only and never written.

    Args:
        db_path: Path to the ``Photos.sqlite`` database.

    Returns:
        One :class:`PhotoRecord` per asset, ordered by ``ZASSET.Z_PK``.
    """
    with _open_readonly(db_path) as conn:
        rows = conn.execute(_QUERY).fetchall()
    return [_row_to_record(row) for row in rows]
