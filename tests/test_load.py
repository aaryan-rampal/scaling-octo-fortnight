"""Unit tests for the pure loading helpers in :mod:`recall.load`.

These exercise label derivation, transcript rendering, and the retain payload
shape using a fake client. Nothing here boots Hindsight or calls OpenRouter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from recall.load import (
    MAX_TRANSCRIPT_CHARS,
    contact_label,
    episode_to_content,
    load_episodes,
)
from recall.schema import Episode, Event


def _event(role: str, content: str, thread_id: str = "+15551234567") -> Event:
    return Event(
        id=f"e-{content}",
        t_utc=datetime(2024, 1, 1, tzinfo=UTC),
        author_role=role,
        content=content,
        thread_id=thread_id,
        reply_to=None,
        raw_ref="chat.db#1",
    )


def _episode(events: list[Event], thread_id: str = "+15551234567") -> Episode:
    return Episode(
        id="ep-1",
        thread_id=thread_id,
        t_start=datetime(2024, 1, 1, 9, 0, tzinfo=UTC),
        t_end=datetime(2024, 1, 1, 9, 5, tzinfo=UTC),
        participants=["other", "self"],
        events=events,
    )


@dataclass
class _FakeClient:
    """Records retain calls so tests can assert on payload shape."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def retain(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_contact_label_phone_and_email_used_verbatim() -> None:
    assert contact_label("+16046526819") == "+16046526819"
    assert contact_label("namiraaa12345@gmail.com") == "namiraaa12345@gmail.com"


def test_contact_label_stable_and_handles_guid_and_empty() -> None:
    guid = "chatABCDEF;-;+16046526819"
    assert contact_label(guid) == "+16046526819"
    assert contact_label(guid) == contact_label(guid)
    assert contact_label("   ") == "unknown"


def test_episode_to_content_maps_roles() -> None:
    ep = _episode(
        [_event("self", "hey"), _event("other", "hi back")],
        thread_id="+15551234567",
    )
    transcript = episode_to_content(ep)
    assert transcript == "me: hey\n+15551234567: hi back"


def test_episode_to_content_truncates_oversized_episode() -> None:
    big = [_event("self", "x" * 200) for _ in range(500)]
    ep = _episode(big)
    transcript = episode_to_content(ep)
    assert len(transcript) <= MAX_TRANSCRIPT_CHARS
    assert "[transcript truncated]" in transcript
    # Head and tail are both preserved.
    assert transcript.startswith("me: ")
    assert transcript.rstrip().endswith("x")


def test_load_episodes_calls_retain_once_per_episode_with_payload() -> None:
    eps = [
        _episode([_event("self", "hello")], thread_id="+16046526819"),
        _episode([_event("other", "yo")], thread_id="alice@example.com"),
    ]
    client = _FakeClient()

    retained = load_episodes(client, eps, "imessage-v0")

    assert retained == 2
    assert len(client.calls) == 2

    first = client.calls[0]
    assert first["bank_id"] == "imessage-v0"
    assert first["content"] == "me: hello"
    assert first["timestamp"] == eps[0].t_start.isoformat()
    assert first["entities"] == [{"text": "+16046526819", "type": "person"}]
    assert first["tags"] == ["imessage", "+16046526819"]
    assert first["metadata"] == {
        "thread_id": "+16046526819",
        "episode_id": "ep-1",
        "n_events": "1",
    }
    # All metadata values are strings (Hindsight requires dict[str, str]).
    assert all(isinstance(v, str) for v in first["metadata"].values())


def test_load_episodes_respects_limit() -> None:
    eps = [_episode([_event("self", str(i))]) for i in range(5)]
    client = _FakeClient()

    assert load_episodes(client, eps, "imessage-v0", limit=2) == 2
    assert len(client.calls) == 2


def test_load_episodes_limit_zero_loads_all() -> None:
    eps = [_episode([_event("self", str(i))]) for i in range(3)]
    client = _FakeClient()

    assert load_episodes(client, eps, "imessage-v0", limit=0) == 3
    assert len(client.calls) == 3
