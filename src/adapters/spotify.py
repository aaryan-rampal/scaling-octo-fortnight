"""Adapter for the Spotify **Extended Streaming History** export.

Reads the ``Streaming_History_*.json`` files from a personal data download,
validates each record into a :class:`~models.spotify.SpotifyStreamRecord`, and
projects the plays onto canonical :class:`~core.schema.Event` rows via
:meth:`SpotifyStreamRecord.to_event`.

This puts Spotify on the **same provenance path as iMessage**: the emitted
events go through ``storage.store.CapsuleStore.add_events`` (durable ``events``
table + ``content_sha`` integrity hash), then ``pipeline.episodes.build_episodes``
windowing, then Hindsight ``retain`` — no source-specific handling downstream.

Export layout (folder, one JSON array per file)::

    Spotify Extended Streaming History/
        Streaming_History_Audio_2024.json
        Streaming_History_Video_2024.json
        ...

CLI::

    python -m adapters.spotify --export "/path/to/Spotify Extended Streaming History"
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx

from core.schema import Event, write_events_jsonl
from models.spotify import SpotifyStreamRecord
from storage.persist import persist_events

#: Files holding streaming history within the export folder.
_HISTORY_GLOB = "Streaming_History_*.json"

#: Default: drop plays shorter than this many ms. Most very-short plays are
#: skips / accidental taps and add noise to the principles graph without signal.
DEFAULT_MIN_MS_PLAYED = 30_000

DEFAULT_OUTPUT = "data/spotify_events.jsonl"

#: On-disk cache of ``artist name -> short vibe``. Keyed by artist so re-running
#: over the same artists never re-calls the LLM (the call is the only cost).
DEFAULT_VIBE_CACHE = Path("data/artist_vibes.json")

#: OpenRouter chat-completions endpoint + model, matching ``runtime.hindsight``.
_OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
VIBE_MODEL = "google/gemini-3.5-flash"

#: One vibe is short and stable; this caps the response so a stray essay can't
#: pollute the cache or the rendered line.
_VIBE_MAX_CHARS = 60

_VIBE_PROMPT = (
    "Describe this music artist's overall vibe in 2-5 words capturing genre and "
    "energy, e.g. 'high-energy EDM/pop' or 'moody alt-R&B'. Reply with ONLY the "
    "phrase, no punctuation at the end, no quotes. Artist: {artist}"
)

#: Signature of an artist->vibe resolver. Injected in tests to avoid network.
VibeResolver = Callable[[str], str]


def load_vibe_cache(path: str | Path = DEFAULT_VIBE_CACHE) -> dict[str, str]:
    """Load the cached ``artist -> vibe`` map, or ``{}`` if none exists yet."""
    cache_path = Path(path)
    if not cache_path.exists():
        return {}
    with open(cache_path, encoding="utf-8") as fh:
        return json.load(fh)


def save_vibe_cache(cache: dict[str, str], path: str | Path = DEFAULT_VIBE_CACHE) -> None:
    """Write the ``artist -> vibe`` map to disk (sorted, pretty) for reuse."""
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(cache.items())), fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def fetch_artist_vibe(artist: str) -> str:
    """Ask gemini (via OpenRouter) for one short vibe phrase for ``artist``.

    Uses the same provider/key path as ``runtime.hindsight`` (the reader's
    ``OPENROUTER_API_KEY``). This is the only networked call in this module; it
    is never invoked in tests (callers inject a resolver) and is gated behind the
    cache so a cached artist is free.

    Args:
        artist: Artist display name to characterise.

    Returns:
        A short taste phrase, e.g. ``"high-energy EDM/pop"``.

    Raises:
        RuntimeError: If ``OPENROUTER_API_KEY`` is unset.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set; cannot fetch artist vibes")
    resp = httpx.post(
        _OPENROUTER_CHAT_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": VIBE_MODEL,
            "messages": [{"role": "user", "content": _VIBE_PROMPT.format(artist=artist)}],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return text.strip().strip("\"'").rstrip(".")[:_VIBE_MAX_CHARS]


def resolve_vibes(
    artists: Iterator[str] | list[str],
    *,
    cache: dict[str, str],
    resolver: VibeResolver = fetch_artist_vibe,
) -> dict[str, str]:
    """Return a vibe for each artist, calling ``resolver`` only for cache misses.

    Mutates ``cache`` in place with any newly resolved artists so the caller can
    persist it. Idempotent: a second call over the same artists makes no
    resolver calls.

    Args:
        artists: Artist names to resolve (duplicates are fine).
        cache: Existing ``artist -> vibe`` map; updated in place.
        resolver: Callable that produces a vibe for an uncached artist. Defaults
            to the live OpenRouter call; tests inject a stub.

    Returns:
        The subset of ``cache`` covering the requested artists.
    """
    out: dict[str, str] = {}
    for artist in artists:
        if not artist:
            continue
        if artist not in cache:
            cache[artist] = resolver(artist)
        out[artist] = cache[artist]
    return out


def enrich_records(
    records: list[SpotifyStreamRecord],
    *,
    cache_path: str | Path = DEFAULT_VIBE_CACHE,
    resolver: VibeResolver = fetch_artist_vibe,
) -> list[SpotifyStreamRecord]:
    """Stamp each music record with its artist's cached vibe (in place).

    Resolves one vibe per *unique* artist, persists the refreshed cache, and sets
    ``record.artist_vibe`` so ``to_event`` carries it into ``additional_data`` and
    ``content_line``. Non-music records and records without an artist are left
    untouched.

    Args:
        records: Validated streaming-history records to enrich.
        cache_path: Where the ``artist -> vibe`` cache lives.
        resolver: Vibe lookup for cache misses (injected in tests).

    Returns:
        The same ``records`` list, now with ``artist_vibe`` populated.
    """
    cache = load_vibe_cache(cache_path)
    unique = {r.artist_name for r in records if r.kind == "music" and r.artist_name}
    vibes = resolve_vibes(sorted(unique), cache=cache, resolver=resolver)
    save_vibe_cache(cache, cache_path)
    for record in records:
        if record.artist_name in vibes:
            record.artist_vibe = vibes[record.artist_name]
    return records


def _history_files(export_dir: Path) -> list[Path]:
    """Return the streaming-history JSON files in ``export_dir``, sorted by name.

    Accepts either the export root (which contains the
    ``Spotify Extended Streaming History`` folder) or that folder directly.
    """
    direct = sorted(export_dir.glob(_HISTORY_GLOB))
    if direct:
        return direct
    nested = export_dir / "Spotify Extended Streaming History"
    return sorted(nested.glob(_HISTORY_GLOB))


def read_records(export_dir: str | Path) -> Iterator[SpotifyStreamRecord]:
    """Yield every streaming-history record across all files in ``export_dir``.

    Each file is a JSON array of raw record dicts; each validates directly into a
    :class:`SpotifyStreamRecord` by field alias.
    """
    export_path = Path(export_dir)
    files = _history_files(export_path)
    if not files:
        raise FileNotFoundError(
            f"No {_HISTORY_GLOB!r} files found under {export_path} "
            "(expected a Spotify Extended Streaming History export)."
        )
    for path in files:
        with open(path, encoding="utf-8") as fh:
            for raw in json.load(fh):
                yield SpotifyStreamRecord.model_validate(raw)


def records_to_events(
    records: Iterator[SpotifyStreamRecord] | list[SpotifyStreamRecord],
    min_ms_played: int = DEFAULT_MIN_MS_PLAYED,
) -> list[Event]:
    """Project records onto canonical events, dropping trivially-short plays.

    Args:
        records: Validated streaming-history records.
        min_ms_played: Plays shorter than this (ms) are skipped as noise. Pass
            ``0`` to keep everything.

    Returns:
        Canonical events, one per kept play.
    """
    return [r.to_event() for r in records if r.ms_played >= min_ms_played]


def ingest(
    export_dir: str | Path,
    min_ms_played: int = DEFAULT_MIN_MS_PLAYED,
    *,
    enrich: bool = False,
    cache_path: str | Path = DEFAULT_VIBE_CACHE,
    resolver: VibeResolver = fetch_artist_vibe,
) -> list[Event]:
    """Read an export folder and return canonical events for its plays.

    Args:
        export_dir: Export root or the ``Spotify Extended Streaming History``
            folder.
        min_ms_played: Minimum play length (ms) to keep.
        enrich: When ``True``, resolve a cached per-artist vibe (one LLM call per
            uncached artist) and stamp it onto each event before projecting.
        cache_path: Where the ``artist -> vibe`` cache lives (used when enriching).
        resolver: Vibe lookup for cache misses; tests inject a stub to stay offline.

    Returns:
        Canonical events ready for ``store.add_events`` / the episode pipeline.
    """
    records: Iterator[SpotifyStreamRecord] | list[SpotifyStreamRecord] = read_records(export_dir)
    if enrich:
        records = enrich_records(list(records), cache_path=cache_path, resolver=resolver)
    return records_to_events(records, min_ms_played=min_ms_played)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the Spotify adapter entry point."""
    parser = argparse.ArgumentParser(description="Ingest a Spotify export to events.")
    parser.add_argument(
        "--export",
        required=True,
        help="Path to the export root or the Streaming History folder.",
    )
    parser.add_argument(
        "--min-ms-played",
        type=int,
        default=DEFAULT_MIN_MS_PLAYED,
        help="Drop plays shorter than this many ms (0 = keep all).",
    )
    parser.add_argument("--out", default=DEFAULT_OUTPUT, help="Output JSONL path.")
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Skip persisting events to the durable SQLite store.",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Resolve a cached per-artist vibe (one OpenRouter call per uncached artist).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: ingest a Spotify export to JSONL and the durable store."""
    args = _parse_args(argv)
    events = ingest(args.export, min_ms_played=args.min_ms_played, enrich=args.enrich)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    written = write_events_jsonl(events, args.out)
    print(f"Wrote {written} events to {args.out}")
    if not args.no_store:
        stored = persist_events(events)
        print(f"Persisted {stored} events to the unified events table")


if __name__ == "__main__":
    main()
