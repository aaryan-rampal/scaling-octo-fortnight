"""Unit tests for the ``recall`` CLI argparse wiring.

These confirm that each subcommand parses its flags and dispatches to the right
handler with the expected attributes. Handlers are patched so nothing here runs
the real pipeline, hits the network, or boots Hindsight.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from recall import cli


def test_ingest_dispatches_to_ingest_handler() -> None:
    with patch.object(cli, "_handle_ingest") as handler:
        cli.main(["ingest", "--top-n", "3"])
    handler.assert_called_once()
    args = handler.call_args.args[0]
    assert args.top_n == 3


def test_ingest_accepts_since() -> None:
    with patch.object(cli, "_handle_ingest") as handler:
        cli.main(["ingest", "--top-n", "5", "--since", "2024-01-01"])
    args = handler.call_args.args[0]
    assert args.top_n == 5
    assert args.since == "2024-01-01"


def test_episodes_dispatches_with_gap_minutes() -> None:
    with patch.object(cli, "_handle_episodes") as handler:
        cli.main(["episodes", "--gap-minutes", "45"])
    handler.assert_called_once()
    args = handler.call_args.args[0]
    assert args.gap_minutes == 45


def test_load_dispatches_with_bank_and_limit() -> None:
    with patch.object(cli, "_handle_load") as handler:
        cli.main(["load", "--bank", "imessage-v0", "--limit", "150"])
    handler.assert_called_once()
    args = handler.call_args.args[0]
    assert args.bank == "imessage-v0"
    assert args.limit == 150


def test_show_dispatches_with_bank() -> None:
    with patch.object(cli, "_handle_show") as handler:
        cli.main(["show", "--bank", "imessage-v0"])
    handler.assert_called_once()
    args = handler.call_args.args[0]
    assert args.bank == "imessage-v0"


def test_all_dispatches_with_full_pipeline_args() -> None:
    with patch.object(cli, "_handle_all") as handler:
        cli.main(["all", "--top-n", "5", "--limit", "150", "--bank", "imessage-v0"])
    handler.assert_called_once()
    args = handler.call_args.args[0]
    assert args.top_n == 5
    assert args.limit == 150
    assert args.bank == "imessage-v0"


def test_missing_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        cli.main([])
