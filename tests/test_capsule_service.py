"""Tests for the capsule build/file-save service (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from poc_demo.server.capsules import (
    UnsupportedMediaError,
    build_capsule,
    kind_for_mime,
    save_media_file,
)


def test_kind_for_mime() -> None:
    assert kind_for_mime("image/jpeg") == "photo"
    assert kind_for_mime("audio/m4a") == "audio"
    assert kind_for_mime("video/quicktime") == "video"
    assert kind_for_mime("text/plain") == "text"
    assert kind_for_mime("application/pdf") is None
    assert kind_for_mime(None) is None


def test_save_media_file_writes_bytes_and_record(tmp_path: Path) -> None:
    media = save_media_file("cap1", "photo.jpg", b"\xff\xd8data", "image/jpeg", media_root=tmp_path)
    assert media.kind == "photo"
    assert media.byte_size == len(b"\xff\xd8data")
    assert (tmp_path / media.file_path).read_bytes() == b"\xff\xd8data"
    # stored under the capsule id, keeping the extension
    assert media.file_path.startswith("cap1/")
    assert media.file_path.endswith(".jpg")


def test_save_media_file_rejects_unsupported(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMediaError):
        save_media_file("cap1", "x.pdf", b"%PDF", "application/pdf", media_root=tmp_path)


def test_build_capsule_assembles_media(tmp_path: Path) -> None:
    capsule = build_capsule(
        place_name="Marina",
        lat=37.8,
        lng=-122.4,
        uploads=[
            ("a.jpg", b"img", "image/jpeg"),
            ("note.txt", b"hello", "text/plain"),
        ],
        media_root=tmp_path,
    )
    assert capsule.place_name == "Marina"
    assert capsule.created_at.tzinfo is not None
    kinds = sorted(m.kind for m in capsule.media)
    assert kinds == ["photo", "text"]
    for m in capsule.media:
        assert (tmp_path / m.file_path).exists()
        assert m.capsule_id == capsule.id


def test_build_capsule_with_no_media(tmp_path: Path) -> None:
    capsule = build_capsule("Empty Place", None, None, [], media_root=tmp_path)
    assert capsule.media == []
    assert capsule.lat is None
