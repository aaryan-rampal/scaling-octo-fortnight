"""Tests for the Claude-chat adaptor (adaptors.llm_chats).

Pins the canonical mapping from a ClaudeConversation to canonical Events:
role/source/thread_id/raw_ref, the reply_to root sentinel, deterministic ids,
content rendering with privacy rules (thinking dropped, tool blocks reduced to a
marker), empty-skip, and the empty-conversation case.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from adaptors.llm_chats import _event_id, ingest_export, to_chat_events
from models.llm_export import ClaudeConversation
from recall.schema import Event

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "llm_export"

ROOT_SENTINEL = "00000000-0000-4000-8000-000000000000"
NORMAL_UUID = "77885cb3-2acb-40c2-b1ec-826900e8a251"
EMPTY_UUID = "6690d9d4-e7a8-404f-ab1e-b0971dbdb5fa"
DEEP_UUID = "f6522b2c-60c7-4c79-bc60-5d72be0790cb"


def _conv(uuid: str, messages: list[dict]) -> ClaudeConversation:
    return ClaudeConversation.model_validate(
        {
            "uuid": uuid,
            "name": "t",
            "created_at": "2025-11-23T17:43:50Z",
            "updated_at": "2025-11-23T17:44:00Z",
            "chat_messages": messages,
        }
    )


def _msg(
    uuid: str,
    sender: str,
    text: str,
    *,
    content: list[dict] | None = None,
    parent: str | None = ROOT_SENTINEL,
) -> dict:
    return {
        "uuid": uuid,
        "sender": sender,
        "text": text,
        "content": content if content is not None else [{"type": "text", "text": text}],
        "created_at": "2025-11-23T17:43:52Z",
        "parent_message_uuid": parent,
    }


# ---- role / source / thread_id / raw_ref ----------------------------------


def test_author_role_mapping() -> None:
    conv = _conv(
        "c1",
        [
            _msg("m1", "human", "ask"),
            _msg("m2", "assistant", "answer", parent="m1"),
        ],
    )
    events = to_chat_events(conv)
    roles = {e.raw_ref: e.author_role for e in events}
    assert roles["claude:c1#m1"] == "self"
    assert roles["claude:c1#m2"] == "other"


def test_source_is_claude() -> None:
    conv = _conv("c1", [_msg("m1", "human", "hi")])
    events = to_chat_events(conv)
    assert all(e.source == "claude" for e in events)
    assert all(isinstance(e, Event) for e in events)


def test_thread_id_is_conversation_uuid() -> None:
    conv = _conv("conv-xyz", [_msg("m1", "human", "hi")])
    events = to_chat_events(conv)
    assert all(e.thread_id == "conv-xyz" for e in events)


def test_raw_ref_format() -> None:
    conv = _conv("conv-xyz", [_msg("m1", "human", "hi")])
    events = to_chat_events(conv)
    assert events[0].raw_ref == "claude:conv-xyz#m1"


# ---- reply_to sentinel ----------------------------------------------------


def test_reply_to_root_sentinel_becomes_none() -> None:
    conv = _conv("c1", [_msg("m1", "human", "hi", parent=ROOT_SENTINEL)])
    events = to_chat_events(conv)
    assert events[0].reply_to is None


def test_reply_to_null_becomes_none() -> None:
    conv = _conv("c1", [_msg("m1", "human", "hi", parent=None)])
    events = to_chat_events(conv)
    assert events[0].reply_to is None


def test_reply_to_real_parent_preserved() -> None:
    conv = _conv(
        "c1",
        [
            _msg("m1", "human", "ask"),
            _msg("m2", "assistant", "answer", parent="m1"),
        ],
    )
    by_ref = {e.raw_ref: e for e in to_chat_events(conv)}
    assert by_ref["claude:c1#m2"].reply_to == "m1"


# ---- timestamps -----------------------------------------------------------


def test_t_utc_is_tz_aware_utc() -> None:
    conv = _conv("c1", [_msg("m1", "human", "hi")])
    ev = to_chat_events(conv)[0]
    assert ev.t_utc.tzinfo is not None
    assert ev.t_utc.utcoffset() == UTC.utcoffset(None)


# ---- deterministic ids ----------------------------------------------------


def test_event_id_deterministic() -> None:
    assert _event_id("c1", "m1") == _event_id("c1", "m1")


def test_event_id_differs_per_message() -> None:
    assert _event_id("c1", "m1") != _event_id("c1", "m2")


def test_ids_stable_across_calls() -> None:
    conv = _conv("c1", [_msg("m1", "human", "hi")])
    first = {e.raw_ref: e.id for e in to_chat_events(conv)}
    second = {e.raw_ref: e.id for e in to_chat_events(conv)}
    assert first == second


def test_ids_unique_per_message() -> None:
    conv = _conv(
        "c1",
        [_msg("m1", "human", "a"), _msg("m2", "assistant", "b", parent="m1")],
    )
    ids = [e.id for e in to_chat_events(conv)]
    assert len(ids) == len(set(ids))


# ---- content rendering: top-level text is primary -------------------------


def test_top_level_text_is_primary_body() -> None:
    conv = _conv(
        "c1",
        [_msg("m1", "human", "FULL_SUPERSET_BODY", content=[{"type": "text", "text": "blk"}])],
    )
    ev = to_chat_events(conv)[0]
    assert ev.content == "FULL_SUPERSET_BODY"


def test_blank_top_level_falls_back_to_blocks() -> None:
    conv = _conv(
        "c1",
        [
            _msg(
                "m1",
                "human",
                "",
                content=[
                    {"type": "text", "text": "block one"},
                    {"type": "text", "text": "block two"},
                ],
            )
        ],
    )
    ev = to_chat_events(conv)[0]
    assert ev.content is not None
    assert "block one" in ev.content
    assert "block two" in ev.content


# ---- privacy: thinking dropped, tool blocks reduced to marker -------------


def test_thinking_text_never_leaks() -> None:
    conv = _conv(
        "c1",
        [
            _msg(
                "m1",
                "assistant",
                "",
                content=[
                    {"type": "thinking", "text": "SECRET_THINKING_DO_NOT_LEAK"},
                    {"type": "text", "text": "visible reply"},
                ],
                parent=None,
            )
        ],
    )
    events = to_chat_events(conv)
    assert events, "message with a visible text block should be emitted"
    assert all(e.content is not None for e in events)
    joined = "\n".join(e.content for e in events if e.content is not None)
    assert "SECRET_THINKING_DO_NOT_LEAK" not in joined
    assert "visible reply" in joined


def test_tool_result_raw_text_never_leaks_marker_present() -> None:
    conv = _conv(
        "c1",
        [
            _msg(
                "m1",
                "assistant",
                "",
                content=[
                    {
                        "type": "tool_use",
                        "name": "web_search",
                        "input": {"q": "SECRET_TOOL_INPUT"},
                    },
                    {
                        "type": "tool_result",
                        "name": "web_search",
                        "content": [{"type": "text", "text": "SECRET_TOOL_OUTPUT"}],
                    },
                ],
                parent=None,
            )
        ],
    )
    events = to_chat_events(conv)
    assert events, "a tool marker is non-empty content, so the message is emitted"
    assert all(e.content is not None for e in events)
    joined = "\n".join(e.content for e in events if e.content is not None)
    assert "SECRET_TOOL_OUTPUT" not in joined
    assert "SECRET_TOOL_INPUT" not in joined
    assert "[tool: web_search]" in joined


# ---- empty-skip and empty conversation ------------------------------------


def test_empty_rendered_message_skipped() -> None:
    conv = _conv(
        "c1",
        [
            _msg("m1", "human", "   ", content=[{"type": "thinking", "text": "x"}], parent=None),
            _msg("m2", "human", "real text", parent="m1"),
        ],
    )
    events = to_chat_events(conv)
    refs = {e.raw_ref for e in events}
    assert "claude:c1#m1" not in refs
    assert "claude:c1#m2" in refs


def test_empty_conversation_yields_no_events() -> None:
    conv = _conv("c1", [])
    assert to_chat_events(conv) == []


# ---- ingest_export on the real fixture ------------------------------------


def test_ingest_export_returns_chat_events() -> None:
    events = ingest_export(FIXTURE_DIR)
    assert events
    assert all(isinstance(e, Event) for e in events)
    assert all(e.source == "claude" for e in events)


def test_ingest_export_thread_ids_present() -> None:
    events = ingest_export(FIXTURE_DIR)
    thread_ids = {e.thread_id for e in events}
    assert NORMAL_UUID in thread_ids
    assert DEEP_UUID in thread_ids


def test_ingest_export_empty_conversation_contributes_nothing() -> None:
    events = ingest_export(FIXTURE_DIR)
    assert all(e.thread_id != EMPTY_UUID for e in events)


def test_ingest_export_roles_only_self_or_other() -> None:
    events = ingest_export(FIXTURE_DIR)
    assert {e.author_role for e in events} <= {"self", "other"}
