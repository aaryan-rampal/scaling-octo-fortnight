"""Load windowed iMessage episodes into an embedded Hindsight bank.

Reads episodes from JSONL, renders each as a plain-text transcript, and
retains them into a Hindsight memory bank with per-contact entities and tags.
The retain path calls OpenRouter, so the CLI defaults to a small ``--limit`` to
keep ordinary runs cheap; pass a larger limit (or ``--limit 0``) for a full
load.
"""

from __future__ import annotations

import argparse
import contextlib
import json
from typing import Any, Protocol

from core.schema import Episode
from runtime.hindsight import embedded_hindsight

DEFAULT_BANK = "imessage-v0"
DEFAULT_INPUT = "data/episodes.jsonl"
DEFAULT_LIMIT = 20

# Cap a single transcript so one oversized episode (e.g. the 1042-event chat)
# does not produce an enormous retain payload. We keep a head and tail slice so
# both the start and the most recent context of the conversation survive.
MAX_TRANSCRIPT_CHARS = 12000
_TRUNCATION_MARKER = "... [transcript truncated] ..."


class RetainClient(Protocol):
    """Minimal client surface used by :func:`load_episodes`.

    Structurally compatible with ``hindsight_client.Hindsight`` so the real
    client satisfies it, while letting tests substitute a fake without booting
    the embedded server. ``load_episodes`` only ever calls ``retain`` with
    keyword arguments, so the fake accepts ``**kwargs``.
    """

    def retain(self, *args: Any, **kwargs: Any) -> Any:
        """Retain one memory; see ``Hindsight.retain`` for full semantics."""
        ...


def contact_label(thread_id: str) -> str:
    """Derive a stable, readable contact label from an episode thread id.

    Thread ids encode the chat identifier — a phone number, an email, or an
    iMessage GUID. Phone numbers and emails are used verbatim. For GUID-style
    ids (``chat...;-;<addr>`` or ``;`` / ``-`` separated forms) the last
    address-like segment is used. No real names are fabricated.

    Args:
        thread_id: The episode's ``thread_id``.

    Returns:
        A stable label such as ``"+16046526819"`` or ``"alice@example.com"``.
    """
    label = thread_id.strip()
    if not label:
        return "unknown"
    if "@" in label or label.startswith("+"):
        return label
    # GUID-ish identifiers: take the trailing segment after a separator.
    for sep in (";-;", ";", "/"):
        if sep in label:
            label = label.rsplit(sep, 1)[-1]
    return label or thread_id


def _event_line(role: str | None, content: str | None, contact: str) -> str:
    """Render one transcript line, mapping ``self`` to ``me``.

    Args:
        role: Author role; ``"self"`` renders as ``"me"``, anything else
            (including ``None``) renders as the contact label.
        content: Message body; ``None`` renders as an empty body.
        contact: Contact label for non-self speakers.

    Returns:
        A ``"{speaker}: {content}"`` transcript line.
    """
    speaker = "me" if role == "self" else contact
    return f"{speaker}: {content or ''}"


def episode_to_content(episode: Episode) -> str:
    """Render an episode as a plain-text transcript, one line per event.

    Each line is ``"{speaker}: {content}"`` where ``speaker`` is ``"me"`` for
    self-authored events and the contact label otherwise. Oversized transcripts
    are truncated to :data:`MAX_TRANSCRIPT_CHARS` by keeping a head and tail
    slice joined by a marker, preserving both the opening and the most recent
    context of the conversation.

    Args:
        episode: The episode to render.

    Returns:
        The transcript text.
    """
    contact = contact_label(episode.thread_id)
    lines = [_event_line(e.author_role, e.content, contact) for e in episode.events]
    transcript = "\n".join(lines)
    if len(transcript) <= MAX_TRANSCRIPT_CHARS:
        return transcript

    budget = MAX_TRANSCRIPT_CHARS - len(_TRUNCATION_MARKER)
    head_len = budget // 2
    tail_len = budget - head_len
    head = transcript[:head_len].rsplit("\n", 1)[0]
    tail = transcript[-tail_len:].split("\n", 1)[-1]
    return f"{head}\n{_TRUNCATION_MARKER}\n{tail}"


def load_episodes(
    client: RetainClient,
    episodes: list[Episode],
    bank_id: str,
    limit: int | None = None,
) -> int:
    """Retain episodes into a Hindsight bank, one retain call per episode.

    Args:
        client: A client exposing :meth:`retain` (real or fake).
        episodes: Episodes to load.
        bank_id: Target bank id.
        limit: If set, only the first ``limit`` episodes are loaded. ``None``
            or ``0`` loads all of them.

    Returns:
        The number of episodes retained.
    """
    selected = episodes[:limit] if limit else episodes
    for episode in selected:
        contact = contact_label(episode.thread_id)
        client.retain(
            bank_id=bank_id,
            content=episode_to_content(episode),
            timestamp=episode.t_start.isoformat(),
            entities=[{"text": contact, "type": "person"}],
            tags=["imessage", contact],
            metadata={
                "thread_id": episode.thread_id,
                "episode_id": episode.id,
                "n_events": str(len(episode.events)),
            },
        )
    return len(selected)


def read_episodes_jsonl(path: str) -> list[Episode]:
    """Read episodes from a JSONL file produced by the windowing step."""
    episodes: list[Episode] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                episodes.append(Episode.from_dict(json.loads(line)))
    return episodes


def main() -> None:
    """CLI entry point: load episodes from JSONL into an embedded bank.

    Defaults to a small ``--limit`` because each retain calls OpenRouter (cost
    and latency). Pass ``--limit 0`` to load every episode.
    """
    parser = argparse.ArgumentParser(description="Load episodes into Hindsight.")
    parser.add_argument("--bank", default=DEFAULT_BANK)
    parser.add_argument("--in", dest="in_path", default=DEFAULT_INPUT)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Max episodes to load (0 = all). Defaults small to stay cheap.",
    )
    args = parser.parse_args()

    episodes = read_episodes_jsonl(args.in_path)
    print(f"read {len(episodes)} episodes from {args.in_path}")

    with embedded_hindsight() as client:
        # Bank may already exist from a prior run; loading proceeds regardless.
        with contextlib.suppress(Exception):
            client.create_bank(bank_id=args.bank)
        retained = load_episodes(client, episodes, args.bank, limit=args.limit)

    print(f"retained {retained} episodes into bank {args.bank!r}")


if __name__ == "__main__":
    main()
