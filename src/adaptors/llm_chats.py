"""Canonical mapping from a parsed Claude export to :class:`ChatEvent` rows.

This is the *mapping* layer that sits on top of the faithful parse models in
``models.llm_export``. It turns each :class:`ClaudeMessage` into a canonical
:class:`ChatEvent` (``source="claude"``), applying the project's conventions for
roles, thread ids, reply links, deterministic ids, and — most importantly — the
privacy rules that decide what message content is allowed to be persisted.

Privacy is the reason this layer exists separately from parsing. The export
contains material we must never store: the model's private ``thinking`` and the
raw inputs/outputs of tool calls (search queries, fetched page text, etc.). The
renderer here keeps only the human-visible conversational text and reduces any
tool activity to a bare ``[tool: <name>]`` marker, so a stored row can show that
a tool ran without leaking what it sent or received.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from models.chat_event import ChatEvent
from models.llm_export import ClaudeConversation, ClaudeExport, ClaudeMessage

#: Sentinel ``parent_message_uuid`` the export uses for a thread's root message.
#: It is not a real message id, so the mapping treats it (like ``null``) as
#: "no parent" and stores ``reply_to=None``.
ROOT_SENTINEL = "00000000-0000-4000-8000-000000000000"

#: Block types whose only canonical contribution is a ``[tool: <name>]`` marker.
#: Their inputs/outputs are privacy-sensitive and are never rendered.
_TOOL_BLOCK_TYPES = frozenset({"tool_use", "tool_result"})

#: Sender → canonical author role. ``human`` is the account owner ("self");
#: the assistant is the counterpart ("other"), mirroring iMessage's mapping.
_ROLE_BY_SENDER = {"human": "self", "assistant": "other"}


def _event_id(thread_id: str, message_uuid: str) -> str:
    """Build a stable, unique event id for a message.

    The id is the first 16 hex chars of the SHA-256 of ``"<thread>|<message>"``,
    matching the truncation idiom used by ``recall.ingest._event_id``. The key
    is fully determined by identifiers (not content), so re-ingesting the same
    export yields identical ids — making the canonical store idempotent on id —
    while distinct messages get distinct ids.

    Args:
        thread_id: The conversation uuid the message belongs to.
        message_uuid: The message's own uuid.

    Returns:
        A 16-character hexadecimal id.
    """
    key = f"{thread_id}|{message_uuid}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _render_content(message: ClaudeMessage) -> str:
    """Render the privacy-filtered, persistable body of a message.

    Rendering rules, in order:

    1. The primary body is the message's top-level ``text``. It is the full,
       already-assembled turn, so when present it is used verbatim.
    2. If that top-level text is blank/whitespace, fall back to concatenating the
       ``text`` of each ``type == "text"`` content block (newline-joined).
    3. Append one ``[tool: <name>]`` marker per ``tool_use`` / ``tool_result``
       block. The marker is the *only* thing tool blocks contribute — their
       inputs, results and nested content are dropped.
    4. ``thinking`` blocks (and any other non-text, non-tool block) contribute
       nothing.

    Body text is emitted first, followed by tool markers, matching natural
    reading order.

    Args:
        message: The parsed Claude message.

    Returns:
        The rendered body, which may be empty if the message has no visible text
        and no tool activity. Callers skip messages that render empty.
    """
    parts: list[str] = []

    body = message.text
    if body and body.strip():
        parts.append(body)
    else:
        block_texts = [
            b.text for b in message.content if b.type == "text" and b.text and b.text.strip()
        ]
        if block_texts:
            parts.append("\n".join(block_texts))

    for block in message.content:
        if block.type in _TOOL_BLOCK_TYPES:
            parts.append(f"[tool: {block.name}]")

    return "\n".join(parts).strip()


def _reply_to(parent_message_uuid: str | None) -> str | None:
    """Normalize a parent uuid to a canonical ``reply_to`` value.

    Both an absent parent (``None``) and the root sentinel uuid mean "no parent"
    and map to ``None``; any real uuid is preserved.

    Args:
        parent_message_uuid: The raw ``parent_message_uuid`` from the export.

    Returns:
        The parent message uuid, or ``None`` for a thread root.
    """
    if parent_message_uuid is None or parent_message_uuid == ROOT_SENTINEL:
        return None
    return parent_message_uuid


def to_chat_events(conversation: ClaudeConversation) -> list[ChatEvent]:
    """Map one conversation's messages to canonical :class:`ChatEvent` rows.

    Each message becomes at most one event. A message whose rendered content is
    empty (e.g. only a ``thinking`` block, or an empty body) is skipped, so the
    result can be shorter than the input and an empty conversation yields ``[]``.

    Args:
        conversation: A parsed conversation from the Claude export.

    Returns:
        The conversation's messages as canonical events, in input order, with
        empty-rendering messages dropped.
    """
    thread_id = conversation.uuid
    events: list[ChatEvent] = []
    for message in conversation.chat_messages:
        content = _render_content(message)
        if not content:
            continue
        events.append(
            ChatEvent(
                id=_event_id(thread_id, message.uuid),
                t_utc=message.created_at,
                author_role=_ROLE_BY_SENDER[message.sender],
                content=content,
                thread_id=thread_id,
                reply_to=_reply_to(message.parent_message_uuid),
                raw_ref=f"claude:{thread_id}#{message.uuid}",
                source="claude",
            )
        )
    return events


def ingest_export(export_dir: str | Path) -> list[ChatEvent]:
    """Load a Claude export directory and map every conversation to events.

    Args:
        export_dir: Path to the unpacked export directory containing
            ``conversations.json``.

    Returns:
        Canonical events flat-mapped across all conversations, ready to persist.

    Raises:
        FileNotFoundError: If the export directory has no ``conversations.json``.
    """
    export = ClaudeExport.from_dir(export_dir)
    events: list[ChatEvent] = []
    for conversation in export.conversations:
        events.extend(to_chat_events(conversation))
    return events
