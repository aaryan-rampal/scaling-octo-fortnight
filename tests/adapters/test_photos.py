"""Tests for the Apple Photos adapter against a synthetic fixture database.

The fixture mirrors the exact ``Photos.sqlite`` columns used by the adapter (a
slice of ZASSET, ZADDITIONALASSETATTRIBUTES, ZPERSON, ZDETECTEDFACE), so tests
exercise the real queries without depending on the user's live library.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from adapters import photos as photos_mod
from adapters.photos import (
    APPLE_EPOCH_OFFSET,
    GPS_SENTINEL,
    _parse_vision_response,
    _resolve_image_path,
    apple_date_to_utc,
    enrich_photos,
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


def test_ingest_skips_null_date_created(tmp_path: Path) -> None:
    # Regression (BUG.md #2): an asset with NULL ZDATECREATED must be skipped,
    # not crash the whole ingest with a TypeError.
    db = tmp_path / "Photos.sqlite"
    _build_fixture_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO ZASSET VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (6, "uuid-null-date", None, 1.0, 2.0, "D6", "IMG_6.heic", 10, 20, 0, 0, 0, 0),
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILENAME) VALUES (?, ?, ?)",
        (6, 6, "original_6.HEIC"),
    )
    conn.commit()
    conn.close()

    records = {r.id: r for r in ingest_photos(str(db))}
    assert "uuid-null-date" not in records  # skipped, no crash
    assert "uuid-1" in records  # the rest still ingested


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


def _photo(uuid: str, *, kind: str = "photo", rel: str = "originals/D/o.jpg") -> PhotoRecord:
    """Build a minimal record for the vision-enrichment tests."""
    return PhotoRecord(
        id=uuid,
        captured_at=datetime(2024, 1, 1, tzinfo=UTC),
        lat=49.0,
        lng=-123.0,
        original_filename="o.jpg",
        original_path=rel,
        width=10,
        height=10,
        is_favorite=False,
        is_hidden=False,
        is_trashed=False,
        kind=kind,  # type: ignore[arg-type]
        people=[],
        raw_ref="photos.sqlite#1",
    )


def _write_image(library_root: Path, rel: str) -> None:
    """Write a tiny non-empty binary at the record's resolved on-disk path."""
    target = library_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")


def test_resolve_image_path_prefers_original_when_present(tmp_path: Path) -> None:
    rec = _photo("ABCD1234", rel="originals/A/o.jpg")
    _write_image(tmp_path, "originals/A/o.jpg")
    resolved = _resolve_image_path(rec, str(tmp_path))
    assert resolved == tmp_path / "originals/A/o.jpg"


def test_resolve_image_path_falls_back_to_derivative_thumbnail(tmp_path: Path) -> None:
    # Original is iCloud-offloaded (never written); the derivative thumbnail is local.
    rec = _photo("ABCD1234", rel="originals/A/o.jpg")
    deriv = tmp_path / "resources" / "derivatives" / "A" / "ABCD1234_1_105_c.jpeg"
    deriv.parent.mkdir(parents=True, exist_ok=True)
    deriv.write_bytes(b"\xff\xd8\xff\xe0thumb")
    resolved = _resolve_image_path(rec, str(tmp_path))
    assert resolved == deriv


def test_resolve_image_path_none_when_neither_on_disk(tmp_path: Path) -> None:
    rec = _photo("ABCD1234", rel="originals/A/o.jpg")
    assert _resolve_image_path(rec, str(tmp_path)) is None


def test_parse_vision_response_handles_plain_and_fenced_json() -> None:
    plain = _parse_vision_response('{"description": "A dog on a beach", "tags": ["Dog", "Beach"]}')
    assert plain is not None
    assert plain["description"] == "A dog on a beach"
    assert plain["tags"] == ["dog", "beach"]  # lowercased
    fenced = _parse_vision_response('```json\n{"description": "x", "tags": []}\n```')
    assert fenced is not None
    assert fenced["description"] == "x"
    assert fenced["tags"] == []


def test_parse_vision_response_returns_none_on_malformed_reply() -> None:
    # A single bad model reply must degrade to None (skip the photo), not crash.
    assert _parse_vision_response(None) is None
    assert _parse_vision_response("") is None
    assert _parse_vision_response("Sorry, I cannot help with that.") is None
    assert _parse_vision_response('{"description": "x", "tags": [') is None  # truncated JSON
    assert _parse_vision_response("[1, 2, 3]") is None  # JSON but not an object


def test_enrich_photos_calls_model_once_and_sets_fields(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "lib"
    _write_image(library, "originals/D/o.jpg")
    calls: list[str] = []

    def fake_call(data_url: str, api_key: str, model: str) -> dict[str, object]:
        calls.append(data_url)
        assert data_url.startswith("data:")  # binary was read + encoded
        return {"description": "Friends at a cafe", "tags": ["cafe", "friends"]}

    monkeypatch.setattr(photos_mod, "_call_vision_model", fake_call)
    cache = tmp_path / "cache.json"
    out = enrich_photos(
        [_photo("p1")],
        library_root=str(library),
        cache_path=cache,
        api_key="sk-test",
    )
    assert out[0].vision_description == "Friends at a cafe"
    assert out[0].vision_tags == ["cafe", "friends"]
    assert len(calls) == 1
    # vision fields surface in the canonical event's additional_data.
    ad = out[0].to_event().additional_data
    assert ad["vision_description"] == "Friends at a cafe"
    assert ad["vision_tags"] == ["cafe", "friends"]


def test_enrich_photos_caches_by_id_no_recall(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "lib"
    _write_image(library, "originals/D/o.jpg")
    cache = tmp_path / "cache.json"
    calls = {"n": 0}

    def fake_call(data_url: str, api_key: str, model: str) -> dict[str, object]:
        calls["n"] += 1
        return {"description": "d", "tags": ["t"]}

    monkeypatch.setattr(photos_mod, "_call_vision_model", fake_call)
    enrich_photos([_photo("p1")], library_root=str(library), cache_path=cache, api_key="sk")
    assert cache.exists()
    # Second run on the same id must not call the model again.
    out2 = enrich_photos([_photo("p1")], library_root=str(library), cache_path=cache, api_key="sk")
    assert calls["n"] == 1
    assert out2[0].vision_description == "d"


def test_enrich_photos_skips_videos_and_missing_binaries(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "lib"  # no files written -> binary missing

    def boom(*_a, **_k):  # pragma: no cover - must never be called
        raise AssertionError("model must not be called")

    monkeypatch.setattr(photos_mod, "_call_vision_model", boom)
    out = enrich_photos(
        [_photo("vid", kind="video"), _photo("missing", rel="originals/D/gone.jpg")],
        library_root=str(library),
        cache_path=tmp_path / "cache.json",
        api_key="sk",
    )
    assert out[0].vision_description is None  # video skipped
    assert out[1].vision_description is None  # missing binary skipped


def test_enrich_photos_requires_key_for_uncached(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "lib"
    _write_image(library, "originals/D/o.jpg")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        enrich_photos([_photo("p1")], library_root=str(library), cache_path=tmp_path / "c.json")
        raise AssertionError("expected RuntimeError when no key is available")
    except RuntimeError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)


def test_enrich_photos_heic_routes_through_transcode(tmp_path: Path, monkeypatch) -> None:
    # 19/27 slice photos are HEIC; the vision model rejects HEIC, so the binary
    # must be transcoded to a temp JPEG (via sips) before the call.
    library = tmp_path / "lib"
    _write_image(library, "originals/D/o.heic")
    transcoded: list[tuple[str, str]] = []

    def fake_transcode(src: Path, dest: Path) -> None:
        transcoded.append((src.suffix.lower(), dest.suffix.lower()))
        dest.write_bytes(b"\xff\xd8\xff\xe0jpeg-from-heic")  # stand-in JPEG

    sent: list[str] = []

    def fake_call(data_url: str, api_key: str, model: str) -> dict[str, object]:
        sent.append(data_url)
        return {"description": "A beach at sunset", "tags": ["beach"]}

    monkeypatch.setattr(photos_mod, "_transcode_to_jpeg", fake_transcode)
    monkeypatch.setattr(photos_mod, "_call_vision_model", fake_call)
    out = enrich_photos(
        [_photo("h1", rel="originals/D/o.heic")],
        library_root=str(library),
        cache_path=tmp_path / "cache.json",
        api_key="sk",
    )
    # HEIC was transcoded to JPEG, and the JPEG (not the HEIC) was sent.
    assert transcoded == [(".heic", ".jpg")]
    assert len(sent) == 1 and sent[0].startswith("data:image/jpeg")
    assert out[0].vision_description == "A beach at sunset"


def test_enrich_photos_jpeg_sent_without_transcode(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "lib"
    _write_image(library, "originals/D/o.jpg")

    def boom_transcode(src: Path, dest: Path) -> None:  # pragma: no cover
        raise AssertionError("non-HEIC must not be transcoded")

    def fake_call(data_url: str, api_key: str, model: str) -> dict[str, object]:
        return {"description": "d", "tags": []}

    monkeypatch.setattr(photos_mod, "_transcode_to_jpeg", boom_transcode)
    monkeypatch.setattr(photos_mod, "_call_vision_model", fake_call)
    out = enrich_photos(
        [_photo("p1", rel="originals/D/o.jpg")],
        library_root=str(library),
        cache_path=tmp_path / "cache.json",
        api_key="sk",
    )
    assert out[0].vision_description == "d"


def test_sendable_image_passes_through_non_heic_and_cleans_heic_temp(tmp_path: Path) -> None:
    from adapters.photos import _sendable_image

    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"x")
    with _sendable_image(jpg) as sendable:
        assert sendable == jpg  # original passed through unchanged

    heic = tmp_path / "b.heic"
    heic.write_bytes(b"x")

    def stub(src: Path, dest: Path) -> None:
        dest.write_bytes(b"jpeg")

    import adapters.photos as mod

    original = mod._transcode_to_jpeg
    mod._transcode_to_jpeg = stub  # type: ignore[assignment]
    try:
        with _sendable_image(heic) as sendable:
            assert sendable.suffix == ".jpg"
            assert sendable != heic  # a temp copy, not the original
            temp_path = sendable
        assert not temp_path.exists()  # temp deleted on exit
        assert heic.exists()  # original untouched
    finally:
        mod._transcode_to_jpeg = original  # type: ignore[assignment]
