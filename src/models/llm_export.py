"""Faithful Pydantic models of Claude's ``conversations.json`` data export.

These models parse the raw export Claude produces when a user requests their
data. The export is large, deeply nested, and carries many keys that change
release to release (attachments, files, citations, structured tool content,
approval metadata, ...). We deliberately split *faithful parsing* (this module)
from *canonical mapping* (``adaptors.llm_chats``) so the parse layer stays a
thin, honest reflection of the file on disk.

Design stance on strictness, and *why*:

* **Strict where the mapping depends on it.** ``sender`` must be one of the two
  roles we know how to map; an unknown sender (e.g. ``"system"``) is a signal
  the export format changed under us, so we raise rather than guess. Required
  identifiers and timestamps are likewise non-optional.
* **Tolerant everywhere else.** Every model sets ``extra="ignore"`` because the
  export carries dozens of keys we do not model. Tolerating them keeps the
  parser robust across export versions without us chasing every new field; the
  privacy-sensitive ones (tool inputs/outputs, thinking) are dropped at the
  mapping layer regardless, never persisted from here.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ClaudeContentBlock(BaseModel):
    """One content block within a Claude message.

    A message body is a list of these blocks. We only model the three fields the
    canonical mapping reads — ``type`` (to route the block), ``text`` (rendered
    for plain text blocks) and ``name`` (the tool name surfaced in a marker).
    Real blocks carry many more keys (``content``, ``input``, ``is_error``,
    ``tool_use_id``, ``thinking``, ``citations``, ``start_timestamp`` ...); those
    are intentionally ignored here so that privacy-sensitive payloads (tool
    inputs/outputs, model thinking) cannot be read out of this model by accident.

    Attributes:
        type: Block discriminator, e.g. ``"text"``, ``"tool_use"``,
            ``"tool_result"``, ``"thinking"``, ``"voice_note"``. Required.
        text: Plain-text payload for text-bearing blocks, if present.
        name: Tool name for ``tool_use`` / ``tool_result`` blocks, if present.
    """

    model_config = ConfigDict(extra="ignore")

    type: str
    text: str | None = None
    name: str | None = None


class ClaudeMessage(BaseModel):
    """A single message (one human turn or one assistant turn) in a conversation.

    ``sender`` is constrained to the two roles the export uses; any other value
    raises a :class:`pydantic.ValidationError` so a format change is caught at
    parse time instead of producing a silently mis-mapped role. Extra keys
    (``updated_at``, ``attachments``, ``files`` ...) are tolerated and ignored.

    Attributes:
        uuid: Stable per-message identifier within the export.
        sender: Either ``"human"`` or ``"assistant"``; anything else is invalid.
        text: Top-level plain-text body. May be blank, in which case the mapping
            falls back to the message's text content blocks.
        content: Ordered content blocks making up the message body.
        created_at: Message creation time; coerced to a tz-aware datetime.
        parent_message_uuid: UUID of the message this replies to, or ``None``.
            The export uses a sentinel UUID for thread roots; the mapping layer
            normalizes that to ``None``.
    """

    model_config = ConfigDict(extra="ignore")

    uuid: str
    sender: Literal["human", "assistant"]
    text: str
    content: list[ClaudeContentBlock]
    created_at: datetime
    parent_message_uuid: str | None = None


class ClaudeConversation(BaseModel):
    """A single conversation thread from the export.

    Attributes:
        uuid: Stable conversation identifier; used as the canonical thread id.
        name: Human-readable title, which the export may leave ``null``.
        created_at: Conversation creation time, coerced to a tz-aware datetime.
        updated_at: Last-update time, if present.
        chat_messages: Ordered messages in the conversation (possibly empty).
    """

    model_config = ConfigDict(extra="ignore")

    uuid: str
    name: str | None
    created_at: datetime
    updated_at: datetime | None = None
    chat_messages: list[ClaudeMessage]


class ClaudeExport(BaseModel):
    """The whole parsed export: a list of conversations.

    Attributes:
        conversations: Every conversation found in ``conversations.json``.
    """

    model_config = ConfigDict(extra="ignore")

    conversations: list[ClaudeConversation]

    @classmethod
    def from_dir(cls, path: str | Path) -> ClaudeExport:
        """Load and validate ``<path>/conversations.json``.

        The Claude export is a directory; the conversations live in a top-level
        JSON *list* in ``conversations.json``. We read and validate that list
        eagerly so any structural problem (missing file, bad role, malformed
        timestamp) surfaces here rather than deep inside the mapping.

        Args:
            path: Path to the unpacked export directory containing
                ``conversations.json``.

        Returns:
            A validated :class:`ClaudeExport`.

        Raises:
            FileNotFoundError: If ``conversations.json`` is not present under
                ``path``, with a message naming the path we looked for.
            pydantic.ValidationError: If the file contents do not match the
                expected schema (e.g. an unknown ``sender``).
        """
        conversations_path = Path(path) / "conversations.json"
        if not conversations_path.is_file():
            raise FileNotFoundError(
                f"Claude export not found: expected a conversations.json at "
                f"{conversations_path}. Point from_dir() at the unpacked export "
                f"directory."
            )
        raw = json.loads(conversations_path.read_text(encoding="utf-8"))
        return cls(conversations=raw)
