"""Terminal viewer for the v0 raw->memory bank snapshot.

Renders the retained memories grouped by source and proves that each memory
traces back to real ground-truth source rows (the provenance is the point).
Stdlib only so teammates can run it instantly with no installs.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/show_bank.py
    PYTHONPATH=src .venv/bin/python scripts/show_bank.py --source spotify
    PYTHONPATH=src .venv/bin/python scripts/show_bank.py --trace
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT = Path("data/bank_snapshot.json")

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
GREY = "\033[90m"

SOURCE_STYLE = {
    "imessage": ("\U0001f4ac", GREEN),
    "spotify": ("\U0001f3b5", MAGENTA),
    "photos": ("\U0001f4f7", BLUE),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the bank viewer."""
    parser = argparse.ArgumentParser(
        description="Show retained memories and their trace to source data.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help=f"Path to the bank snapshot JSON (default: {DEFAULT_SNAPSHOT}).",
    )
    parser.add_argument(
        "--source",
        choices=sorted(SOURCE_STYLE),
        help="Only show memories from this source.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Expand the full raw_events each memory derives from.",
    )
    return parser.parse_args(argv)


def load_memories(path: Path) -> list[dict[str, Any]]:
    """Load the memory list from the snapshot JSON file.

    Args:
        path: Location of the snapshot file.

    Returns:
        The list of memory dicts.

    Raises:
        SystemExit: If the file is missing or not a JSON list.
    """
    if not path.exists():
        raise SystemExit(f"Snapshot not found: {path} (pass --snapshot PATH).")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON list of memories in {path}.")
    return data


def fmt_when(occurred_start: str | None) -> str:
    """Format an ISO timestamp as a short human date, or 'undated'."""
    if not occurred_start:
        return "undated"
    try:
        dt = datetime.fromisoformat(occurred_start)
    except ValueError:
        return occurred_start
    return dt.strftime("%a %b %d, %Y %H:%M")


def trace_line(raw_events: list[dict[str, Any]]) -> str:
    """Build a one-line 'from source' summary of the first raw event."""
    if not raw_events:
        return f"{GREY}(no source rows){RESET}"
    first = raw_events[0]
    snippet = event_content(first)
    extra = len(raw_events) - 1
    suffix = f" {GREY}(+{extra} more){RESET}" if extra > 0 else ""
    return f"{DIM}↳ from:{RESET} {snippet}{suffix}"


def event_content(event: dict[str, Any]) -> str:
    """Return a readable content string for a raw event.

    Falls back to the original photo filename when content is null, since
    non-conversational sources carry their payload in additional_data.
    """
    content = event.get("content")
    if content:
        return content.strip().replace("\n", " ")
    extra = event.get("additional_data") or {}
    filename = extra.get("original_filename")
    if filename:
        return f"[{filename}]"
    return f"{GREY}(no content){RESET}"


def print_header(memories: list[dict[str, Any]]) -> None:
    """Print the summary banner: totals, per-source counts, traceability."""
    total = len(memories)
    by_source = Counter(m.get("source", "?") for m in memories)
    traceable = sum(1 for m in memories if m.get("raw_events"))
    pct = (traceable / total * 100) if total else 0.0

    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  RECALL — retained memory bank{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"  {BOLD}{total}{RESET} memories  |  {BOLD}{pct:.0f}%{RESET} traceable to source")
    parts = []
    for source, count in by_source.most_common():
        emoji, color = SOURCE_STYLE.get(source, ("•", RESET))
        parts.append(f"{color}{emoji} {source}: {count}{RESET}")
    print("  " + "   ".join(parts))
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}\n")


def print_memory(memory: dict[str, Any], trace: bool) -> None:
    """Print a single memory block, optionally expanding all raw events.

    Args:
        memory: One memory dict from the snapshot.
        trace: When true, list every raw event in full instead of one line.
    """
    text = (memory.get("text") or "").strip()
    when = fmt_when(memory.get("occurred_start"))
    entities = memory.get("entities") or "—"
    fact_type = memory.get("fact_type") or "—"

    print(f"  {BOLD}{text}{RESET}")
    print(f"    {GREY}when {when}  |  who {entities}  |  type {fact_type}{RESET}")
    if trace:
        print_trace(memory.get("raw_events") or [])
    else:
        print(f"    {trace_line(memory.get('raw_events') or [])}")
    print()


def print_trace(raw_events: list[dict[str, Any]]) -> None:
    """Print every raw source row a memory derives from (the money shot)."""
    if not raw_events:
        print(f"    {GREY}↳ (no source rows){RESET}")
        return
    print(f"    {DIM}↳ derived from {len(raw_events)} source row(s):{RESET}")
    for event in raw_events:
        when = fmt_when(event.get("t_utc"))
        print(f"      {YELLOW}•{RESET} {event_content(event)}")
        print(f"        {GREY}{when}  id={event.get('id', '?')}{RESET}")


def render(memories: list[dict[str, Any]], trace: bool) -> None:
    """Render the full viewer: header plus memories grouped by source."""
    print_header(memories)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for memory in memories:
        by_source.setdefault(memory.get("source", "?"), []).append(memory)

    for source in sorted(by_source):
        emoji, color = SOURCE_STYLE.get(source, ("•", RESET))
        group = by_source[source]
        print(f"{color}{BOLD}{emoji}  {source.upper()}  ({len(group)}){RESET}")
        print(f"{color}{'-' * 72}{RESET}")
        for memory in group:
            print_memory(memory, trace)


def main(argv: list[str] | None = None) -> None:
    """Entry point: load the snapshot, filter, and render."""
    args = parse_args(argv)
    memories = load_memories(args.snapshot)
    if args.source:
        memories = [m for m in memories if m.get("source") == args.source]
        if not memories:
            raise SystemExit(f"No memories for source: {args.source}")
    render(memories, args.trace)


if __name__ == "__main__":
    main()
