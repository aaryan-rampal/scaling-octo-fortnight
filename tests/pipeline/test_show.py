"""Tests for the demo rendering helpers in :mod:`pipeline.show`.

These exercise the pure formatting paths with a fake client returning canned
responses, so no embedded server boots and no network call is made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.show import (
    _clean_reflection,
    render_connections,
    render_episodic,
    render_people,
    render_principles,
    render_semantic,
)

BANK = "test-bank"


@dataclass
class FakeResult:
    text: str
    type: str | None = None
    entities: list[str] | None = None
    occurred_start: str | None = None
    mentioned_at: str | None = None


@dataclass
class FakeRecall:
    results: list[FakeResult] = field(default_factory=list)
    entities: dict[str, Any] | None = None


@dataclass
class FakeObservation:
    text: str


@dataclass
class FakeEntity:
    canonical_name: str
    observations: list[FakeObservation] = field(default_factory=list)


@dataclass
class FakeMentalModel:
    name: str
    content: str | None = None


@dataclass
class FakeMentalModelList:
    items: list[FakeMentalModel] = field(default_factory=list)


@dataclass
class FakeReflect:
    text: str | None = None


class FakeClient:
    """Records calls and returns whatever canned responses it was given."""

    def __init__(
        self,
        recall_by_type: dict[str | None, FakeRecall] | None = None,
        mental_models: FakeMentalModelList | None = None,
        reflect: FakeReflect | None = None,
    ) -> None:
        self._recall_by_type = recall_by_type or {}
        self._mental_models = mental_models or FakeMentalModelList()
        self._reflect = reflect or FakeReflect()

    def recall(self, bank_id: str, query: str, **kwargs: Any) -> FakeRecall:
        types = kwargs.get("types")
        key = types[0] if types else None
        return self._recall_by_type.get(key, FakeRecall())

    def list_mental_models(self, bank_id: str, **kwargs: Any) -> FakeMentalModelList:
        return self._mental_models

    def reflect(self, bank_id: str, query: str, **kwargs: Any) -> FakeReflect:
        self.last_reflect_context = kwargs.get("context")
        return self._reflect


def test_render_episodic_lists_text_time_and_people() -> None:
    client = FakeClient(
        recall_by_type={
            "experience": FakeRecall(
                results=[
                    FakeResult(
                        text="Planned a surprise trip to Tahoe.",
                        occurred_start="2024-03-01",
                        entities=["Alex", "Sam"],
                    )
                ]
            )
        }
    )
    out = render_episodic(client, BANK)
    assert "EPISODIC MEMORY" in out
    assert "Planned a surprise trip to Tahoe." in out
    assert "2024-03-01" in out
    assert "Alex, Sam" in out


def test_render_episodic_empty_is_graceful() -> None:
    out = render_episodic(FakeClient(), BANK)
    assert "(no episodic memories surfaced)" in out


def test_render_semantic_lists_facts() -> None:
    client = FakeClient(
        recall_by_type={"world": FakeRecall(results=[FakeResult(text="Sam is vegetarian.")])}
    )
    out = render_semantic(client, BANK)
    assert "SEMANTIC MEMORY" in out
    assert "Sam is vegetarian." in out


def test_render_semantic_empty_is_graceful() -> None:
    out = render_semantic(FakeClient(), BANK)
    assert "(no semantic facts surfaced)" in out


def test_render_people_lists_names_and_observation() -> None:
    client = FakeClient(
        recall_by_type={
            None: FakeRecall(
                entities={
                    "e1": FakeEntity(
                        canonical_name="Alex",
                        observations=[FakeObservation(text="Loves hiking.")],
                    )
                }
            )
        }
    )
    out = render_people(client, BANK)
    assert "PEOPLE" in out
    assert "Alex" in out
    assert "Loves hiking." in out


def test_render_people_empty_is_graceful() -> None:
    out = render_people(FakeClient(), BANK)
    assert "(no people surfaced)" in out


def test_render_principles_lists_models() -> None:
    client = FakeClient(
        mental_models=FakeMentalModelList(
            items=[FakeMentalModel(name="Loyalty", content="Shows up for friends.")]
        )
    )
    out = render_principles(client, BANK)
    assert "PRINCIPLES" in out
    assert "Loyalty" in out
    assert "Shows up for friends." in out


def test_render_principles_empty_is_graceful() -> None:
    out = render_principles(FakeClient(), BANK)
    assert "(none surfaced yet)" in out


def test_render_connections_prints_reflection() -> None:
    client = FakeClient(reflect=FakeReflect(text="A quiet thread of generosity."))
    out = render_connections(client, BANK)
    assert "HINDSIGHT CONNECTIONS" in out
    assert "A quiet thread of generosity." in out


def test_render_connections_empty_is_graceful() -> None:
    out = render_connections(FakeClient(reflect=FakeReflect(text="")), BANK)
    assert "(no connection synthesized)" in out


def test_render_connections_strips_tool_narration() -> None:
    narrated = "I need to call recall() first.**Answer:** A thread of generosity."
    out = render_connections(FakeClient(reflect=FakeReflect(text=narrated)), BANK)
    assert "I need to call recall()" not in out
    assert "**Answer:** A thread of generosity." in out


def test_clean_reflection_keeps_text_without_marker() -> None:
    assert _clean_reflection("Plain answer.") == "Plain answer."


def test_render_connections_grounds_reflect_with_recalled_facts() -> None:
    client = FakeClient(
        recall_by_type={
            "experience": FakeRecall(results=[FakeResult(text="Bet $10k to make a friend.")]),
            "world": FakeRecall(results=[FakeResult(text="Switched from CS to arts.")]),
        },
        reflect=FakeReflect(text="**Insight:** efficiency runs through everything."),
    )
    out = render_connections(client, BANK)
    assert "efficiency runs through everything." in out
    assert client.last_reflect_context is not None
    assert "Bet $10k to make a friend." in client.last_reflect_context
    assert "Switched from CS to arts." in client.last_reflect_context
