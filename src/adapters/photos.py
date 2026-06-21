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

import base64
import json
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

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


def _row_to_record(row: sqlite3.Row) -> PhotoRecord | None:
    """Map one joined query row to a :class:`PhotoRecord`, or skip it.

    Returns ``None`` when ``ZDATECREATED`` is NULL — the asset has no capture
    time, so there is nothing to anchor an event in time. This mirrors how the
    adapter already skips rows it cannot make a usable record from, rather than
    letting one malformed row crash the whole ingest.
    """
    if row["date_created"] is None:
        return None
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
    records = (_row_to_record(row) for row in rows)
    return [r for r in records if r is not None]


# --- Vision enrichment -------------------------------------------------------
#
# Raw photo rows are just ``{lat, lng, filename}``, so a photo memory reads "took
# a photo at coordinates X". A cheap vision model turns the image into a one-line
# description plus a few tags, written additively into the record's vision fields
# (the renderer surfaces them). The call is lazy and cached by photo id so a huge
# library (thousands of assets) never re-pays for an already-enriched photo; only
# the photos handed in (i.e. the retained slice, ~18) are ever sent to the model.

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

#: Cheap vision-capable OpenRouter model; overridable via env for tuning/cost.
#: Defaults to the same Gemini Flash family the embedded runtime already uses.
DEFAULT_VISION_MODEL = os.environ.get("RECALL_VISION_MODEL", "google/gemini-3.5-flash")

#: Library-relative ``original_path`` is resolved against this root to find the
#: on-disk binary. Defaults to the standard macOS Photos library; override for a
#: relocated library or a test fixture. The binary is read only to send to the
#: model — never copied or persisted.
DEFAULT_LIBRARY_ROOT = os.environ.get(
    "RECALL_PHOTO_LIBRARY",
    str(Path.home() / "Pictures" / "Photos Library.photoslibrary"),
)

#: Where enriched (description, tags) results are cached, keyed by photo id.
DEFAULT_VISION_CACHE = Path("data/photo_vision_cache.json")

_VISION_PROMPT = (
    "Describe this personal photo in one short, concrete sentence (what is "
    "happening, where, the mood). Then give 3-6 short lowercase tags. "
    'Respond ONLY as JSON: {"description": str, "tags": [str, ...]}.'
)
_VISION_TIMEOUT_S = 60.0

#: ``sips`` binary used to transcode HEIC/HEIF (which most OpenRouter vision
#: models reject) into JPEG. Ships with macOS; no third-party dependency.
SIPS_BINARY = "/usr/bin/sips"

#: Suffixes (lowercased) the vision model cannot ingest directly, so the binary
#: is transcoded to a temp JPEG before sending. Other still formats go as-is.
_TRANSCODE_SUFFIXES = frozenset({".heic", ".heif"})
_SIPS_TIMEOUT_S = 30.0


def _load_vision_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    """Load the photo-id → {description, tags} cache, or empty if absent/corrupt."""
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_vision_cache(cache_path: Path, cache: dict[str, dict[str, Any]]) -> None:
    """Write the cache back to disk, creating the parent directory if needed."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _resolve_image_path(record: PhotoRecord, library_root: str) -> Path:
    """Resolve a record's library-relative ``original_path`` to an on-disk path."""
    return Path(library_root) / record.original_path


def _transcode_to_jpeg(src: Path, dest: Path) -> None:
    """Transcode an image to JPEG at ``dest`` via macOS ``sips``.

    Reads ``src`` and writes only the temp ``dest``; the original is never
    modified. Used for HEIC/HEIF, which most vision models reject.

    Args:
        src: The on-disk original to read.
        dest: Temp path the JPEG is written to.

    Raises:
        RuntimeError: If ``sips`` fails or is unavailable.
    """
    try:
        subprocess.run(
            [SIPS_BINARY, "-s", "format", "jpeg", str(src), "--out", str(dest)],
            check=True,
            capture_output=True,
            timeout=_SIPS_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"sips failed to transcode {src.name} to JPEG: {exc}") from exc


@contextmanager
def _sendable_image(path: Path) -> Iterator[Path]:
    """Yield a path safe to send to the vision model, transcoding HEIC/HEIF.

    HEIC/HEIF originals are transcoded to a temp JPEG (deleted on exit); every
    other still format yields the original path unchanged. The original binary
    is never modified or persisted — only a throwaway temp copy is created for
    the formats that need it.

    Args:
        path: The on-disk original.

    Yields:
        A path to send (the original, or a temp JPEG for HEIC/HEIF).
    """
    if path.suffix.lower() not in _TRANSCODE_SUFFIXES:
        yield path
        return
    with tempfile.TemporaryDirectory() as tmp:
        jpeg = Path(tmp) / f"{path.stem}.jpg"
        _transcode_to_jpeg(path, jpeg)
        yield jpeg


def _encode_image_data_url(path: Path) -> str:
    """Read an image binary and return it as a base64 ``data:`` URL for the API.

    The binary is read solely to embed in the request payload; it is never copied
    or persisted (repo rule: photo binaries stay on disk).
    """
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _parse_vision_response(content: str | None) -> dict[str, Any] | None:
    """Parse the model's JSON reply into ``{description, tags}``, or ``None``.

    Returns ``None`` when the reply is empty, has no JSON object, or is not valid
    JSON — a single malformed reply degrades that one photo to no enrichment
    rather than aborting the whole slice. Tolerates ```` ``` ```` code fences and
    prose around the object.
    """
    if not content:
        return None
    text = content.strip().strip("`")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    description = str(parsed.get("description", "")).strip()
    raw_tags = parsed.get("tags", []) if isinstance(parsed.get("tags"), list) else []
    tags = [str(t).strip().lower() for t in raw_tags if str(t).strip()]
    return {"description": description, "tags": tags}


def _call_vision_model(data_url: str, api_key: str, model: str) -> dict[str, Any] | None:
    """Call the OpenRouter chat-completions API on one image; return description/tags.

    Args:
        data_url: The base64 ``data:`` URL of the image.
        api_key: OpenRouter API key (from ``OPENROUTER_API_KEY``).
        model: OpenRouter vision-capable model id.

    Returns:
        A ``{"description": str, "tags": list[str]}`` dict, or ``None`` when the
        response carries no usable content (error body, empty choices, null
        content, or an unparseable reply) — one bad photo is skipped rather than
        aborting the whole enrichment pass.

    Raises:
        httpx.HTTPError: If the HTTP request itself fails.
    """
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    resp = httpx.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=_VISION_TIMEOUT_S,
    )
    resp.raise_for_status()
    choices = resp.json().get("choices") or []
    if not choices:
        return None
    content = (choices[0].get("message") or {}).get("content")
    return _parse_vision_response(content if isinstance(content, str) else None)


def enrich_photos(
    records: list[PhotoRecord],
    *,
    library_root: str = DEFAULT_LIBRARY_ROOT,
    model: str = DEFAULT_VISION_MODEL,
    cache_path: Path = DEFAULT_VISION_CACHE,
    api_key: str | None = None,
) -> list[PhotoRecord]:
    """Add a vision description + tags to each photo, lazily and cached by id.

    Only the records passed in are ever sent to the model, so callers control
    cost by enriching just the retained slice (~18) rather than the whole library
    (thousands). Already-cached photos (and videos, which carry no still frame)
    are skipped; a missing on-disk binary is skipped rather than fatal. The cache
    (``photo id → {description, tags}``) is persisted so re-runs cost nothing.

    Args:
        records: Photo/video records to enrich (typically the retained slice).
        library_root: Root the library-relative ``original_path`` resolves against.
        model: OpenRouter vision-capable model id.
        cache_path: JSON cache keyed by photo id.
        api_key: OpenRouter key; falls back to ``OPENROUTER_API_KEY`` in the env.

    Returns:
        The same records, each with ``vision_description`` / ``vision_tags`` set
        when enrichment succeeded (additive — other fields are untouched).

    Raises:
        RuntimeError: If a model call is needed but no API key is available.
    """
    cache = _load_vision_cache(cache_path)
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    enriched: list[PhotoRecord] = []
    dirty = False
    for record in records:
        result = cache.get(record.id)
        if result is None and record.kind == "photo":
            result = _enrich_one(record, library_root, model, key, cache)
            dirty = dirty or result is not None
        enriched.append(_apply_vision(record, result))
    if dirty:
        _save_vision_cache(cache_path, cache)
    return enriched


def _enrich_one(
    record: PhotoRecord,
    library_root: str,
    model: str,
    api_key: str | None,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Enrich a single uncached photo, writing the result into ``cache`` in place.

    Returns the ``{description, tags}`` result, or ``None`` when the binary is
    missing on disk (skipped, not fatal). Raises if a call is needed but no key
    is set.
    """
    path = _resolve_image_path(record, library_root)
    if not path.exists():
        return None
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set; cannot vision-enrich photos "
            f"(needed for uncached photo {record.id})"
        )
    with _sendable_image(path) as sendable:
        data_url = _encode_image_data_url(sendable)
        result = _call_vision_model(data_url, api_key, model)
    if result is None:
        return None
    cache[record.id] = result
    return result


def _apply_vision(record: PhotoRecord, result: dict[str, Any] | None) -> PhotoRecord:
    """Return a copy of ``record`` with vision fields set from ``result`` (or as-is)."""
    if not result:
        return record
    return record.model_copy(
        update={
            "vision_description": result.get("description") or None,
            "vision_tags": list(result.get("tags", [])),
        }
    )
