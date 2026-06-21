"""Parse-time model for a single Apple Photos asset (``PhotoRecord``).

A ``PhotoRecord`` is the canonical raw_data row for one photo or video drawn from
the local ``Photos.sqlite``. It is intentionally *not* a ``ChatEvent``: photos are
not conversational, so they get their own model and their own table rather than
being forced into the message schema.

Pydantic is used (over the frozen dataclasses elsewhere) because the source rows
come straight out of a third-party SQLite schema we do not control: strict
validation catches a column drifting type or a flag arriving as something other
than a bool, failing loud at ingest instead of silently corrupting the store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PhotoRecord(BaseModel):
    """One photo or video asset's metadata, with provenance back to the source.

    No binary is ever copied: ``original_path`` references the original on disk so
    the recall DB stays small (same philosophy as ``Media.file_path``). Only
    *named* people are recorded; anonymous face clusters are dropped because their
    cluster ids carry no human meaning.

    Attributes:
        id: Stable identifier for the asset (the Photos ``ZUUID``).
        captured_at: Timezone-aware UTC capture time (Apple Core Data epoch
            converted to UTC at ingest).
        lat: Latitude in degrees, or ``None`` when GPS is absent (the source's
            ``(-180, -180)`` sentinel is mapped to ``None``).
        lng: Longitude in degrees, or ``None`` when GPS is absent.
        original_filename: The user-facing original filename (``ZORIGINALFILENAME``).
        original_path: Library-relative path to the original on disk,
            ``originals/<ZDIRECTORY>/<ZFILENAME>``. The binary is never read.
        width: Pixel width of the asset.
        height: Pixel height of the asset.
        is_favorite: Whether the user flagged the asset as a favorite.
        is_hidden: Whether the asset is in the Hidden album.
        is_trashed: Whether the asset is in the Recently Deleted album.
        kind: ``"photo"`` or ``"video"`` (from the source ``ZKIND`` enum).
        people: Display names of *named* people detected in the asset; anonymous
            clusters are excluded. Empty when no named person is present.
        raw_ref: Exact source reference, ``photos.sqlite#<ZASSET.Z_PK>`` — the
            provenance link that must survive even if the library is rebuilt.
    """

    id: str
    captured_at: datetime
    lat: float | None
    lng: float | None
    original_filename: str
    original_path: str
    width: int
    height: int
    is_favorite: bool
    is_hidden: bool
    is_trashed: bool
    kind: Literal["photo", "video"]
    people: list[str]
    raw_ref: str
