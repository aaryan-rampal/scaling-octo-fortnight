"""Tests for the faithful Pydantic models of the Claude export (models.llm_export).

These models parse the raw ``conversations.json`` produced by Claude's data
export. They are strict about the fields the mapping depends on (sender,
timestamps, block type) while tolerating the many extra keys the export carries
(updated_at, attachments, files, approval_key, ...).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.llm_export import (
    ClaudeContentBlock,
    ClaudeConversation,
    ClaudeExport,
    ClaudeMessage,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "llm_export"

NORMAL_UUID = "77885cb3-2acb-40c2-b1ec-826900e8a251"
TOOL_UUID = "f8d8b5fb-93e3-4644-be55-c3454e5d4a94"
EMPTY_UUID = "6690d9d4-e7a8-404f-ab1e-b0971dbdb5fa"
DEEP_UUID = "f6522b2c-60c7-4c79-bc60-5d72be0790cb"
VOICE_UUID = "492dc5a4-d7fd-4240-8499-f5e5e2b28013"


def test_content_block_minimal() -> None:
    block = ClaudeContentBlock(type="text", text="hi")
    assert block.type == "text"
    assert block.text == "hi"
    assert block.name is None


def test_content_block_name_only() -> None:
    block = ClaudeContentBlock(type="tool_use", name="web_search")
    assert block.type == "tool_use"
    assert block.name == "web_search"
    assert block.text is None


def test_content_block_tolerates_extras() -> None:
    block = ClaudeContentBlock.model_validate(
        {
            "type": "tool_result",
            "name": "user_time_v0",
            "content": [{"type": "text", "text": "x"}],
            "is_error": False,
            "tool_use_id": None,
        }
    )
    assert block.type == "tool_result"
    assert block.name == "user_time_v0"


def test_content_block_type_required() -> None:
    with pytest.raises(ValidationError):
        ClaudeContentBlock.model_validate({"text": "no type here"})


def test_message_parses_human() -> None:
    msg = ClaudeMessage.model_validate(
        {
            "uuid": "m1",
            "sender": "human",
            "text": "hello",
            "content": [{"type": "text", "text": "hello"}],
            "created_at": "2025-11-23T17:43:52Z",
            "parent_message_uuid": None,
        }
    )
    assert msg.sender == "human"
    assert msg.text == "hello"
    assert isinstance(msg.created_at, datetime)
    assert msg.created_at.tzinfo is not None
    assert len(msg.content) == 1
    assert isinstance(msg.content[0], ClaudeContentBlock)


def test_message_tolerates_extra_keys() -> None:
    msg = ClaudeMessage.model_validate(
        {
            "uuid": "m2",
            "sender": "assistant",
            "text": "hi back",
            "content": [],
            "created_at": "2025-11-23T17:43:55Z",
            "parent_message_uuid": "m1",
            "updated_at": "2025-11-23T17:43:56Z",
            "attachments": [],
            "files": [],
        }
    )
    assert msg.sender == "assistant"
    assert msg.parent_message_uuid == "m1"


def test_message_unknown_sender_fails() -> None:
    with pytest.raises(ValidationError):
        ClaudeMessage.model_validate(
            {
                "uuid": "m3",
                "sender": "system",
                "text": "x",
                "content": [],
                "created_at": "2025-11-23T17:43:55Z",
            }
        )


def test_conversation_parses() -> None:
    conv = ClaudeConversation.model_validate(
        {
            "uuid": "c1",
            "name": "A chat",
            "created_at": "2025-11-23T17:43:50Z",
            "updated_at": "2025-11-23T17:44:00Z",
            "chat_messages": [
                {
                    "uuid": "m1",
                    "sender": "human",
                    "text": "hi",
                    "content": [{"type": "text", "text": "hi"}],
                    "created_at": "2025-11-23T17:43:52Z",
                    "parent_message_uuid": None,
                }
            ],
        }
    )
    assert conv.uuid == "c1"
    assert conv.name == "A chat"
    assert len(conv.chat_messages) == 1
    assert isinstance(conv.chat_messages[0], ClaudeMessage)


def test_conversation_name_may_be_null() -> None:
    conv = ClaudeConversation.model_validate(
        {
            "uuid": "c2",
            "name": None,
            "created_at": "2025-11-23T17:43:50Z",
            "updated_at": None,
            "chat_messages": [],
        }
    )
    assert conv.name is None
    assert conv.chat_messages == []


def test_from_dir_loads_fixture() -> None:
    export = ClaudeExport.from_dir(FIXTURE_DIR)
    by_uuid = {c.uuid: c for c in export.conversations}
    assert NORMAL_UUID in by_uuid
    assert TOOL_UUID in by_uuid
    assert EMPTY_UUID in by_uuid
    assert DEEP_UUID in by_uuid
    assert VOICE_UUID in by_uuid


def test_from_dir_counts() -> None:
    export = ClaudeExport.from_dir(FIXTURE_DIR)
    by_uuid = {c.uuid: c for c in export.conversations}
    assert len(by_uuid[NORMAL_UUID].chat_messages) == 6
    assert len(by_uuid[EMPTY_UUID].chat_messages) == 0
    assert len(by_uuid[DEEP_UUID].chat_messages) == 14


def test_from_dir_tool_blocks_preserved() -> None:
    export = ClaudeExport.from_dir(FIXTURE_DIR)
    by_uuid = {c.uuid: c for c in export.conversations}
    block_types = {b.type for m in by_uuid[TOOL_UUID].chat_messages for b in m.content}
    assert "tool_use" in block_types
    assert "tool_result" in block_types
