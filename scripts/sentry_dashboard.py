"""Create the RETURN demo observability dashboard in Sentry via the API.

Builds a single-pane dashboard showing the views worth demoing — pipeline stage
transactions, LLM/gen_ai spend, live logs, errors, and key pipeline measurements —
all from the instrumentation already wired across build/retain/mint/link.

The Sentry MCP is read-only for dashboards, and the ``SENTRY_DSN`` only *sends*
data; creating a dashboard needs a Sentry **auth token** with ``org:write`` (or
``dashboards`` scope). Provide it via ``SENTRY_AUTH_TOKEN``.

Run::

    SENTRY_AUTH_TOKEN=sntrys_... .venv/bin/python scripts/sentry_dashboard.py

Reads no project data and makes no pipeline calls — pure Sentry API. Safe to run
while a pipeline is in flight; it never touches the local run.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ORG = os.environ.get("SENTRY_ORG", "amazon-0r")
PROJECT_ID = os.environ.get("SENTRY_PROJECT_ID", "4511603486818304")
REGION = os.environ.get("SENTRY_REGION_URL", "https://us.sentry.io")
TITLE = "RETURN — Pipeline Observability"


def _w(title, display_type, widget_type, queries, layout, *, interval="1h"):
    """Build one dashboard widget dict.

    Args:
        title: Widget header.
        display_type: One of line/area/table/big_number.
        widget_type: Dataset — "transaction-like"/"spans"/"error-events"/"logs".
        queries: List of query dicts (name/conditions/fields/aggregates/columns).
        layout: {x, y, w, h} grid placement.
        interval: Time bucket for time-series widgets.

    Returns:
        A widget dict matching the Sentry dashboards API schema.
    """
    return {
        "title": title,
        "displayType": display_type,
        "widgetType": widget_type,
        "interval": interval,
        "queries": queries,
        "layout": layout,
    }


def _q(name, fields, aggregates, conditions, columns=None, order_by=""):
    """Build one widget query dict."""
    return {
        "name": name,
        "fields": fields,
        "aggregates": aggregates,
        "columns": columns or [],
        "conditions": conditions,
        "orderby": order_by,
    }


def build_dashboard() -> dict:
    """Assemble the full demo dashboard (title + widgets) to the API schema."""
    widgets = [
        # Row 0 — big-number headline counters.
        _w(
            "Pipeline transactions (24h)", "big_number", "transaction-like",
            [_q("", ["count()"], ["count()"],
                "transaction:[build_all_sources_db,retain_slice,mint_principles,link_principles]")],
            {"x": 0, "y": 0, "w": 1, "h": 1},
        ),
        _w(
            "LLM / gen_ai calls (24h)", "big_number", "spans",
            [_q("", ["count()"], ["count()"], "span.op:gen_ai.chat")],
            {"x": 1, "y": 0, "w": 1, "h": 1},
        ),
        _w(
            "Total tokens (24h)", "big_number", "spans",
            [_q("", ["sum(gen_ai.usage.total_tokens)"], ["sum(gen_ai.usage.total_tokens)"],
                "has:gen_ai.usage.total_tokens")],
            {"x": 2, "y": 0, "w": 1, "h": 1},
        ),
        _w(
            "Errors (24h)", "big_number", "error-events",
            [_q("", ["count()"], ["count()"], "")],
            {"x": 3, "y": 0, "w": 1, "h": 1},
        ),
        # Row 1 — pipeline stage timing (the stage timeline).
        _w(
            "Stage duration by transaction", "table", "transaction-like",
            [_q("stages",
                ["transaction", "count()", "avg(transaction.duration)",
                 "max(transaction.duration)"],
                ["count()", "avg(transaction.duration)", "max(transaction.duration)"],
                "transaction:[build_all_sources_db,retain_slice,mint_principles,link_principles]",
                ["transaction"], "-avg(transaction.duration)")],
            {"x": 0, "y": 1, "w": 2, "h": 2},
        ),
        # Row 1 — LLM latency over time.
        _w(
            "gen_ai call latency over time", "line", "spans",
            [_q("", ["avg(span.duration)", "count()"], ["avg(span.duration)", "count()"],
                "span.op:gen_ai.chat")],
            {"x": 2, "y": 1, "w": 2, "h": 2},
        ),
        # Row 3 — token usage split.
        _w(
            "Token usage (input vs output)", "area", "spans",
            [_q("", ["sum(gen_ai.usage.input_tokens)", "sum(gen_ai.usage.output_tokens)"],
                ["sum(gen_ai.usage.input_tokens)", "sum(gen_ai.usage.output_tokens)"],
                "has:gen_ai.usage.input_tokens")],
            {"x": 0, "y": 3, "w": 2, "h": 2},
        ),
        # Row 3 — recent errors table.
        _w(
            "Recent issues", "table", "error-events",
            [_q("errors", ["title", "count()", "last_seen()"], ["count()", "last_seen()"],
                "", ["title"], "-last_seen()")],
            {"x": 2, "y": 3, "w": 2, "h": 2},
        ),
    ]
    return {"title": TITLE, "widgets": widgets, "projects": [int(PROJECT_ID)]}


def main() -> None:
    """POST the dashboard to Sentry, printing the created dashboard URL."""
    token = os.environ.get("SENTRY_AUTH_TOKEN")
    if not token:
        sys.exit(
            "SENTRY_AUTH_TOKEN not set. Create one at "
            "https://amazon-0r.sentry.io/settings/auth-tokens/ with dashboards/org:write "
            "scope, then: SENTRY_AUTH_TOKEN=sntrys_... .venv/bin/python scripts/sentry_dashboard.py"
        )

    url = f"{REGION}/api/0/organizations/{ORG}/dashboards/"
    body = json.dumps(build_dashboard()).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        sys.exit(f"Sentry API {exc.code}: {detail}")

    dash_id = created.get("id")
    print(f"Created dashboard {dash_id!r}: {TITLE}")
    print(f"  {REGION.replace('us.', 'amazon-0r.')}/dashboard/{dash_id}/")


if __name__ == "__main__":
    main()
