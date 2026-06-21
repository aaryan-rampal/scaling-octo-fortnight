"""Adapter for the Spotify **Extended Streaming History** export.

Reads the ``Streaming_History_*.json`` files from a personal data download,
validates each record into a :class:`~models.spotify.SpotifyStreamRecord`, and
projects the plays onto canonical :class:`~recall.schema.Event` rows via
:meth:`SpotifyStreamRecord.to_event`.

This puts Spotify on the **same provenance path as iMessage**: the emitted
events go through ``recall.store.CapsuleStore.add_events`` (durable ``events``
table + ``content_sha`` integrity hash), then ``recall.episodes.build_episodes``
windowing, then Hindsight ``retain`` — no source-specific handling downstream.

Export layout (folder, one JSON array per file)::

    Spotify Extended Streaming History/
        Streaming_History_Audio_2024.json
        Streaming_History_Video_2024.json
        ...

CLI::

    python -m adaptors.spotify --export "/path/to/Spotify Extended Streaming History"
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

from adaptors._persist import persist_events
from models.spotify import SpotifyStreamRecord
from recall.schema import Event, write_events_jsonl

#: Files holding streaming history within the export folder.
_HISTORY_GLOB = "Streaming_History_*.json"

#: Default: drop plays shorter than this many ms. Most very-short plays are
#: skips / accidental taps and add noise to the principles graph without signal.
DEFAULT_MIN_MS_PLAYED = 30_000

DEFAULT_OUTPUT = "data/spotify_events.jsonl"


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
) -> list[Event]:
    """Read an export folder and return canonical events for its plays.

    Args:
        export_dir: Export root or the ``Spotify Extended Streaming History``
            folder.
        min_ms_played: Minimum play length (ms) to keep.

    Returns:
        Canonical events ready for ``store.add_events`` / the episode pipeline.
    """
    return records_to_events(read_records(export_dir), min_ms_played=min_ms_played)


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: ingest a Spotify export to JSONL and the durable store."""
    args = _parse_args(argv)
    events = ingest(args.export, min_ms_played=args.min_ms_played)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    written = write_events_jsonl(events, args.out)
    print(f"Wrote {written} events to {args.out}")
    if not args.no_store:
        stored = persist_events(events)
        print(f"Persisted {stored} events to the unified events table")


if __name__ == "__main__":
    main()
