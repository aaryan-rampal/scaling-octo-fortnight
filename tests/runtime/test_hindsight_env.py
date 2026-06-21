"""Unit tests for the embedded Hindsight env configuration.

These tests assert env-var wiring only; they never boot the server or touch the
network. The retain-mission knob steers fact extraction away from reading casual
slang as literal kinship (Track D of the enrichment contract).
"""

from __future__ import annotations

import os

from runtime.hindsight import RETAIN_MISSION, _apply_openrouter_env


def test_apply_openrouter_env_sets_retain_mission(monkeypatch) -> None:
    """The retain-mission env var carries our slang/kinship instruction."""
    monkeypatch.delenv("HINDSIGHT_API_RETAIN_MISSION", raising=False)

    _apply_openrouter_env("dummy-key", "llm-model", "embeddings-model")

    assert os.environ["HINDSIGHT_API_RETAIN_MISSION"] == RETAIN_MISSION


def test_retain_mission_mentions_slang_terms() -> None:
    """The instruction names the endearment terms it must not read literally."""
    mission = RETAIN_MISSION.lower()
    assert "literal" in mission
    for term in ("bro", "brother", "bestie", "fam", "sis"):
        assert term in mission


def test_apply_openrouter_env_leaves_model_config_untouched(monkeypatch) -> None:
    """Adding the mission knob must not disturb the decided model/embeddings env."""
    monkeypatch.setenv("HINDSIGHT_API_LLM_MODEL", "stale")
    monkeypatch.setenv("HINDSIGHT_API_EMBEDDINGS_LITELLM_SDK_MODEL", "stale")

    _apply_openrouter_env("dummy-key", "google/gemini-3.5-flash", "qwen/qwen3-embedding-8b")

    assert os.environ["HINDSIGHT_API_LLM_MODEL"] == "google/gemini-3.5-flash"
    embeddings = os.environ["HINDSIGHT_API_EMBEDDINGS_LITELLM_SDK_MODEL"]
    assert embeddings == "openai/qwen/qwen3-embedding-8b"
