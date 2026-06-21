"""Tests for the Apple Photos adapter against a synthetic fixture database.

The fixture mirrors the exact ``Photos.sqlite`` columns used by the adapter (a
slice of ZASSET, ZADDITIONALASSETATTRIBUTES, ZPERSON, ZDETECTEDFACE), so tests
exercise the real queries without depending on the user's live library.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from adaptors.photos import (
    APPLE_EPOCH_OFFSET,
    GPS_SENTINEL,
    apple_date_to_utc,
    ingest_photos,
)
from models.photo import PhotoRecord


def _unix_to_apple(dt: datetime) -> float:
    """Convert a UTC datetime to an Apple Core Data epoch float (seconds)."""
    return dt.timestamp() - APPLE_EPOCH_OFFSET


def _build_fixture_db(path: Path) -> None:
    """Create a tiny Photos.sqlite-shaped fixture covering the adapter's cases.

    Five assets exercise: a GPS photo with a named person, a video, a
    no-GPS sentinel asset, a favorite/hidden/trashed asset, and an asset whose
    only face is an anonymous (null-name) cluster that must be skipped.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY,
            ZUUID TEXT,
            ZDATECREATED REAL,
            ZLATITUDE REAL,
            ZLONGITUDE REAL,
            ZDIRECTORY TEXT,
            ZFILENAME TEXT,
            ZWIDTH INTEGER,
            ZHEIGHT INTEGER,
            ZFAVORITE INTEGER,
            ZHIDDEN INTEGER,
            ZTRASHEDSTATE INTEGER,
            ZKIND INTEGER
        );
        CREATE TABLE ZADDITIONALASSETATTRIBUTES (
            Z_PK INTEGER PRIMARY KEY,
            ZASSET INTEGER,
            ZORIGINALFILENAME TEXT
        );
        CREATE TABLE ZPERSON (
            Z_PK INTEGER PRIMARY KEY,
            ZDISPLAYNAME TEXT
        );
        CREATE TABLE ZDETECTEDFACE (
            Z_PK INTEGER PRIMARY KEY,
            ZASSETFORFACE INTEGER,
            ZPERSONFORFACE INTEGER
        );
        """
    )
    captured = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    apple = _unix_to_apple(captured)
    assets = [
        # pk, uuid, date, lat, lng, dir, file, w, h, fav, hidden, trashed, kind
        (1, "uuid-1", apple, 49.28, -123.12, "D1", "IMG_1.heic", 4032, 3024, 0, 0, 0, 0),
        (2, "uuid-2", apple, 40.71, -74.0, "D2", "VID_2.mov", 1920, 1080, 0, 0, 0, 1),
        (3, "uuid-3", apple, GPS_SENTINEL, GPS_SENTINEL, "D3", "IMG_3.heic", 100, 200, 0, 0, 0, 0),
        (4, "uuid-4", apple, 1.0, 2.0, "D4", "IMG_4.heic", 10, 20, 1, 1, 1, 0),
        (5, "uuid-5", apple, 3.0, 4.0, "D5", "IMG_5.heic", 30, 40, 0, 0, 0, 0),
    ]
    conn.executemany("INSERT INTO ZASSET VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", assets)
    conn.executemany(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILENAME) VALUES (?, ?, ?)",
        [
            (1, 1, "original_1.HEIC"),
            (2, 2, "original_2.MOV"),
            (3, 3, "original_3.HEIC"),
            (4, 4, "original_4.HEIC"),
            (5, 5, "original_5.HEIC"),
        ],
    )
    conn.executemany(
        "INSERT INTO ZPERSON (Z_PK, ZDISPLAYNAME) VALUES (?, ?)",
        [(1, "Alice"), (2, "Bob"), (3, None)],
    )
    conn.executemany(
        "INSERT INTO ZDETECTEDFACE (Z_PK, ZASSETFORFACE, ZPERSONFORFACE) VALUES (?, ?, ?)",
        [
            (1, 1, 1),  # asset 1 -> Alice
            (2, 1, 2),  # asset 1 -> Bob
            (3, 5, 3),  # asset 5 -> anonymous (null name) -> skipped
        ],
    )
    conn.commit()
    conn.close()


def test_apple_date_conversion_known_value() -> None:
    # 2001-01-01 00:00:00 UTC is exactly 0 in Apple's Core Data epoch.
    assert apple_date_to_utc(0.0) == datetime(2001, 1, 1, tzinfo=UTC)
    target = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    assert apple_date_to_utc(target.timestamp() - APPLE_EPOCH_OFFSET) == target


def test_ingest_maps_core_fields(tmp_path: Path) -> None:
    db = tmp_path / "Photos.sqlite"
    _build_fixture_db(db)
    records = {r.id: r for r in ingest_photos(str(db))}

    assert len(records) == 5
    r1 = records["uuid-1"]
    assert r1.captured_at == datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    assert r1.original_filename == "original_1.HEIC"
    assert r1.original_path == "originals/D1/IMG_1.heic"
    assert r1.width == 4032
    assert r1.height == 3024
    assert r1.kind == "photo"
    assert r1.raw_ref == "photos.sqlite#1"


def test_ingest_gps_sentinel_maps_to_none(tmp_path: Path) -> None:
    db = tmp_path / "Photos.sqlite"
    _build_fixture_db(db)
    records = {r.id: r for r in ingest_photos(str(db))}
    # GPS present.
    assert records["uuid-1"].lat == 49.28
    assert records["uuid-1"].lng == -123.12
    # Sentinel -> None.
    assert records["uuid-3"].lat is None
    assert records["uuid-3"].lng is None


def test_ingest_kind_and_flags(tmp_path: Path) -> None:
    db = tmp_path / "Photos.sqlite"
    _build_fixture_db(db)
    records = {r.id: r for r in ingest_photos(str(db))}
    assert records["uuid-2"].kind == "video"
    r4 = records["uuid-4"]
    assert r4.is_favorite is True
    assert r4.is_hidden is True
    assert r4.is_trashed is True
    r1 = records["uuid-1"]
    assert r1.is_favorite is False
    assert r1.is_hidden is False
    assert r1.is_trashed is False


def test_ingest_named_people_only(tmp_path: Path) -> None:
    db = tmp_path / "Photos.sqlite"
    _build_fixture_db(db)
    records = {r.id: r for r in ingest_photos(str(db))}
    # Asset 1 has two named people.
    assert sorted(records["uuid-1"].people) == ["Alice", "Bob"]
    # Asset 5's only face is an anonymous cluster -> no people.
    assert records["uuid-5"].people == []
    # Asset 2 has no faces at all.
    assert records["uuid-2"].people == []


def test_photo_record_is_pydantic_model() -> None:
    r = PhotoRecord(
        id="x",
        captured_at=datetime(2024, 1, 1, tzinfo=UTC),
        lat=None,
        lng=None,
        original_filename="o.heic",
        original_path="originals/D/o.heic",
        width=1,
        height=2,
        is_favorite=False,
        is_hidden=False,
        is_trashed=False,
        kind="photo",
        people=[],
        raw_ref="photos.sqlite#1",
    )
    assert r.kind == "photo"
    assert r.people == []
