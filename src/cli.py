"""Unified ``recall`` command line interface.

Exposes the four pipeline stages — ingest, episodes, load, show — as
subcommands plus an ``all`` subcommand that runs the whole pipeline in
sequence. Each handler delegates to the existing module's public functions
rather than shelling out or duplicating logic.
"""

from __future__ import annotations

import argparse
import contextlib
import os
from datetime import date
from pathlib import Path

from adapters.imessage import DEFAULT_DB_PATH, ingest
from core.schema import read_events_jsonl, write_events_jsonl
from pipeline.episodes import _summary_lines, _write_episodes_jsonl, build_episodes
from pipeline.load import (
    DEFAULT_BANK,
    DEFAULT_LIMIT,
    load_episodes,
    read_episodes_jsonl,
)
from pipeline.show import render_all
from runtime.hindsight import embedded_hindsight
from storage.store import CapsuleStore

EVENTS_PATH = "data/events.jsonl"
EPISODES_PATH = "data/episodes.jsonl"


def _run_ingest(top_n: int, since: date | None, db_path: str, *, persist: bool = True) -> int:
    """Ingest events from ``chat.db``; write JSONL and persist to the store.

    The JSONL stays the input to the ``episodes`` stage (unchanged). When
    ``persist`` is set, the same events are also upserted into the durable SQLite
    store (the ``events`` table), which records a provenance ``content_sha`` per
    message so findings can be traced back to verifiable source text — even if
    ``chat.db`` is later vacuumed or unavailable. Upsert is idempotent on event
    id, so re-ingesting is safe.

    Args:
        top_n: Number of busiest threads to ingest.
        since: Optional lower bound; only messages on or after this date.
        db_path: Path to the SQLite database.
        persist: Whether to also write events into the durable store.

    Returns:
        The number of events written to JSONL.
    """
    events = ingest(top_n, since=since, db_path=db_path)
    os.makedirs(os.path.dirname(EVENTS_PATH) or ".", exist_ok=True)
    written = write_events_jsonl(events, EVENTS_PATH)
    print(f"Wrote {written} events to {EVENTS_PATH}")
    if persist:
        # Re-read from JSONL so the stored rows match exactly what downstream
        # stages consume (single serialized source of truth).
        stored = CapsuleStore().add_events(read_events_jsonl(EVENTS_PATH))
        print(f"Persisted {stored} events to the durable store (events table)")
    return written


def _run_episodes(gap_minutes: int) -> int:
    """Window events from :data:`EVENTS_PATH` into :data:`EPISODES_PATH`.

    Args:
        gap_minutes: Maximum allowed gap, in minutes, within one episode.

    Returns:
        The number of episodes written.
    """
    events = read_events_jsonl(EVENTS_PATH)
    episodes = build_episodes(events, gap_minutes)
    _write_episodes_jsonl(episodes, EPISODES_PATH)
    print(f"read {len(events)} events from {EVENTS_PATH}")
    print(f"wrote {len(episodes)} episodes to {EPISODES_PATH}")
    for line in _summary_lines(episodes):
        print(f"  {line}")
    return len(episodes)


def _run_load(bank: str, limit: int) -> int:
    """Load episodes from :data:`EPISODES_PATH` into an embedded bank.

    Args:
        bank: Target Hindsight bank id.
        limit: Max episodes to load (``0`` loads all).

    Returns:
        The number of episodes retained.
    """
    episodes = read_episodes_jsonl(EPISODES_PATH)
    print(f"read {len(episodes)} episodes from {EPISODES_PATH}")
    with embedded_hindsight() as client:
        with contextlib.suppress(Exception):
            client.create_bank(bank_id=bank)
        retained = load_episodes(client, episodes, bank, limit=limit)
    print(f"retained {retained} episodes into bank {bank!r}")
    return retained


def _run_show(bank: str) -> None:
    """Boot an embedded client and print the demo sections for ``bank``."""
    print(f"Recall — memory networks for bank '{bank}'")
    with embedded_hindsight() as client:
        print(render_all(client, bank))


def _handle_ingest(args: argparse.Namespace) -> None:
    """Dispatch the ``ingest`` subcommand."""
    since = date.fromisoformat(args.since) if args.since else None
    _run_ingest(args.top_n, since, args.db, persist=not args.no_store)


def _handle_episodes(args: argparse.Namespace) -> None:
    """Dispatch the ``episodes`` subcommand."""
    _run_episodes(args.gap_minutes)


def _handle_load(args: argparse.Namespace) -> None:
    """Dispatch the ``load`` subcommand."""
    _run_load(args.bank, args.limit)


def _handle_show(args: argparse.Namespace) -> None:
    """Dispatch the ``show`` subcommand."""
    _run_show(args.bank)


def _handle_all(args: argparse.Namespace) -> None:
    """Dispatch the ``all`` subcommand: ingest -> episodes -> load -> show."""
    since = date.fromisoformat(args.since) if args.since else None
    _run_ingest(args.top_n, since, args.db, persist=not args.no_store)
    _run_episodes(args.gap_minutes)
    _run_load(args.bank, args.limit)
    _run_show(args.bank)


def _find_ui_dir() -> Path | None:
    """Locate the static ``ui/`` directory by walking up from this file.

    Works whether ``recall`` is run from the repo (``ui/`` at the root) or an
    editable install whose ``src`` sits beside it. Returns ``None`` if not found,
    so ``serve`` can still run the API without a UI.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "ui"
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _run_serve(host: str, port: int, token: str | None) -> None:
    """Serve the local app: FastAPI (API + media) with the static UI mounted.

    One origin serves the UI, the API, and uploaded media, so the whole
    local-first app runs from a single command and a phone can reach it at
    ``http://<this-machine-ip>:<port>``. Binding ``0.0.0.0`` (the default) is
    what makes that mobile access work; use ``--host 127.0.0.1`` to keep it
    laptop-only.

    When ``token`` is set (or ``RECALL_TOKEN`` is in the env), the API + media
    are gated behind that passcode — required before exposing the laptop over a
    tunnel for mobile, so data stays local and only the passcode-holder gets in.
    """
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from poc_demo.server import app as app_module

    if token:
        app_module.RECALL_TOKEN = token

    app = app_module.app
    ui_dir = _find_ui_dir()
    if ui_dir is not None:
        # Mount last and at root so /api and /media (registered on import) win;
        # html=True serves index.html at /.
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
        print(f"Serving UI from {ui_dir}")
    else:
        print("No ui/ directory found — serving API only.")
    gate = "passcode-gated" if app_module.RECALL_TOKEN else "OPEN (no passcode)"
    print(f"recall serve → http://{host}:{port}  [{gate}]  (phone: http://<your-ip>:{port})")
    if host == "0.0.0.0" and not app_module.RECALL_TOKEN:
        print("  ⚠ exposed on the network with no passcode — pass --token to protect it.")
    uvicorn.run(app, host=host, port=port)


def _handle_serve(args: argparse.Namespace) -> None:
    """Dispatch the ``serve`` subcommand."""
    _run_serve(args.host, args.port, args.token)


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with one entry per subcommand."""
    parser = argparse.ArgumentParser(prog="recall", description="iMessage memory POC.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest chat.db into events JSONL.")
    p_ingest.add_argument("--top-n", type=int, default=5, help="Top threads by volume.")
    p_ingest.add_argument("--since", default=None, help="Lower bound YYYY-MM-DD.")
    p_ingest.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to chat.db.")
    p_ingest.add_argument(
        "--no-store",
        action="store_true",
        help="Skip persisting events to the durable SQLite store.",
    )
    p_ingest.set_defaults(handler=_handle_ingest)

    p_episodes = sub.add_parser("episodes", help="Window events into episodes.")
    p_episodes.add_argument("--gap-minutes", type=int, default=30)
    p_episodes.set_defaults(handler=_handle_episodes)

    p_load = sub.add_parser("load", help="Load episodes into Hindsight.")
    p_load.add_argument("--bank", default=DEFAULT_BANK)
    p_load.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="0 = all.")
    p_load.set_defaults(handler=_handle_load)

    p_show = sub.add_parser("show", help="Print the memory-network demo.")
    p_show.add_argument("--bank", default=DEFAULT_BANK)
    p_show.set_defaults(handler=_handle_show)

    p_all = sub.add_parser("all", help="Run ingest -> episodes -> load -> show.")
    p_all.add_argument("--top-n", type=int, default=5, help="Top threads by volume.")
    p_all.add_argument("--since", default=None, help="Lower bound YYYY-MM-DD.")
    p_all.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to chat.db.")
    p_all.add_argument(
        "--no-store",
        action="store_true",
        help="Skip persisting events to the durable SQLite store.",
    )
    p_all.add_argument("--gap-minutes", type=int, default=30)
    p_all.add_argument("--bank", default=DEFAULT_BANK)
    p_all.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="0 = all.")
    p_all.set_defaults(handler=_handle_all)

    p_serve = sub.add_parser(
        "serve", help="Run the local app: UI + API + media on one origin."
    )
    p_serve.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address. Default 0.0.0.0 (reachable from phones on the same "
        "wifi); use 127.0.0.1 for laptop-only.",
    )
    p_serve.add_argument("--port", type=int, default=8000, help="Port (default 8000).")
    p_serve.add_argument(
        "--token",
        default=None,
        help="Passcode required for API + media (or set RECALL_TOKEN). Strongly "
        "recommended when binding 0.0.0.0 / exposing over a tunnel.",
    )
    p_serve.set_defaults(handler=_handle_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: parse arguments and dispatch the chosen subcommand."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
