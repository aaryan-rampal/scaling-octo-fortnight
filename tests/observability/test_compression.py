"""Fixture-only tests for observability.compression.

No network, no TTC API spend. The Token Company SDK is faked, so these verify
the gating logic and the passthrough-on-failure contract offline.
"""

from __future__ import annotations

import sys
import types
from typing import Any

from observability import compression


def _install_fake_ttc(
    monkeypatch: Any, *, output: str, input_tokens: int, output_tokens: int
) -> None:
    """Register a fake ``thetokencompany`` module with a stubbed client."""

    class _Resp:
        def __init__(self) -> None:
            self.output = output
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens

    class _Client:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def compress(self, text: str, **_: Any) -> _Resp:
            return _Resp()

    mod = types.ModuleType("thetokencompany")
    mod.TheTokenCompany = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "thetokencompany", mod)


def test_disabled_by_default_passthrough(monkeypatch: Any) -> None:
    monkeypatch.delenv("RETURN_TTC_COMPRESS", raising=False)
    monkeypatch.setenv("TTC_API_KEY", "ttc-test")
    assert compression.compression_enabled() is False
    assert compression.compress_message("hello world") == "hello world"


def test_enabled_requires_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("RETURN_TTC_COMPRESS", "1")
    monkeypatch.delenv("TTC_API_KEY", raising=False)
    assert compression.compression_enabled() is False


def test_compresses_when_enabled(monkeypatch: Any) -> None:
    monkeypatch.setenv("RETURN_TTC_COMPRESS", "1")
    monkeypatch.setenv("TTC_API_KEY", "ttc-test")
    _install_fake_ttc(monkeypatch, output="hi", input_tokens=10, output_tokens=4)
    assert compression.compress_message("hello there world") == "hi"


def test_vendor_failure_falls_back_to_original(monkeypatch: Any) -> None:
    monkeypatch.setenv("RETURN_TTC_COMPRESS", "1")
    monkeypatch.setenv("TTC_API_KEY", "ttc-test")
    mod = types.ModuleType("thetokencompany")

    class _Boom:
        def __init__(self, api_key: str) -> None:
            raise RuntimeError("vendor down")

    mod.TheTokenCompany = _Boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "thetokencompany", mod)
    assert compression.compress_message("keep me") == "keep me"
