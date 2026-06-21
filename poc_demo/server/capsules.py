"""Capsule write-path: turn an HTTP upload into persisted capsule + media.

Keeps the FastAPI handler thin. This module owns id generation, saving uploaded
binaries to the media root, and assembling a :class:`~core.capsule.Capsule`
that :class:`~storage.store.CapsuleStore` persists.

It deliberately stops at persistence. Converting a capsule into canonical
:class:`~core.schema.Event` rows and feeding Hindsight ``retain`` (and the
swarm) is the next stage and is left as a seam — see :func:`build_capsule`'s
return and the TODO in the API layer.
"""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

from core.capsule import MEDIA_KINDS, Capsule, Media

#: Where uploaded binaries are stored, under the gitignored ``data/`` root.
DEFAULT_MEDIA_ROOT = Path("data/media")

#: Map a kind to the MIME prefix we expect, for light validation.
_KIND_BY_PREFIX = {"image": "photo", "audio": "audio", "video": "video", "text": "text"}


def _new_id(*parts: str) -> str:
    """Return a short stable id from the given parts plus the current time."""
    seed = "|".join((*parts, datetime.now(UTC).isoformat()))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def kind_for_mime(mime: str | None) -> str | None:
    """Infer a capsule media kind from a MIME type, or ``None`` if unknown."""
    if not mime:
        return None
    prefix = mime.split("/", 1)[0]
    return _KIND_BY_PREFIX.get(prefix)


class UnsupportedMediaError(ValueError):
    """Raised when an uploaded file's type is not a supported media kind."""


def save_media_file(
    capsule_id: str,
    filename: str,
    content: bytes,
    content_type: str | None,
    media_root: Path = DEFAULT_MEDIA_ROOT,
) -> Media:
    """Write one uploaded file to disk and return its :class:`Media` record.

    Args:
        capsule_id: Owning capsule id; files are grouped under it.
        filename: Original upload filename (used to keep the extension).
        content: Raw file bytes.
        content_type: Reported MIME type, used to classify the media kind.
        media_root: Base directory for stored media.

    Returns:
        A :class:`Media` record pointing at the saved file (path relative to
        ``media_root``).

    Raises:
        UnsupportedMediaError: If the type maps to no supported media kind.
    """
    mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    kind = kind_for_mime(mime)
    if kind is None or kind not in MEDIA_KINDS:
        raise UnsupportedMediaError(f"unsupported media type: {mime!r}")

    media_id = _new_id(capsule_id, filename)
    suffix = Path(filename).suffix or mimetypes.guess_extension(mime) or ""
    rel_path = Path(capsule_id) / f"{media_id}{suffix}"
    abs_path = media_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)

    return Media(
        id=media_id,
        capsule_id=capsule_id,
        kind=kind,
        file_path=str(rel_path),
        mime=mime,
        byte_size=len(content),
    )


def build_capsule(
    place_name: str,
    lat: float | None,
    lng: float | None,
    uploads: list[tuple[str, bytes, str | None]],
    media_root: Path = DEFAULT_MEDIA_ROOT,
) -> Capsule:
    """Assemble (and persist files for) a capsule from a place and uploads.

    Args:
        place_name: User-entered place label.
        lat: Optional latitude.
        lng: Optional longitude.
        uploads: ``(filename, content, content_type)`` tuples for each file.
        media_root: Base directory for stored media.

    Returns:
        A fully-populated :class:`Capsule` (not yet persisted to SQLite — the
        caller hands it to :class:`~storage.store.CapsuleStore`).

    Raises:
        UnsupportedMediaError: If any upload has an unsupported type.
    """
    capsule_id = _new_id(place_name)
    created_at = datetime.now(UTC)
    media = [
        save_media_file(capsule_id, name, content, ctype, media_root)
        for (name, content, ctype) in uploads
    ]
    return Capsule(
        id=capsule_id,
        created_at=created_at,
        place_name=place_name,
        lat=lat,
        lng=lng,
        media=media,
    )
