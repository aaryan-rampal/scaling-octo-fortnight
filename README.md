# Recall — iMessage memory POC

Ingests your local iMessages, builds memory networks with
[Hindsight](https://github.com/vectorize-io/hindsight) (episodic / semantic /
entity / principles), and surfaces non-obvious connections across your
conversations. Runs entirely on your Mac; inference goes through OpenRouter.

```
chat.db  ->  events  ->  episodes  ->  Hindsight (embedded)  ->  recall show / web UI
```

## Prerequisites

- **macOS** with iMessage in use (reads `~/Library/Messages/chat.db`).
- The terminal running this needs **Full Disk Access** (System Settings →
  Privacy & Security → Full Disk Access) to read `chat.db`.
- **uv** (Python 3.13), **Node 22 + pnpm**, **Doppler CLI** (for the API key).
- An **OpenRouter API key** in Doppler (project `berkeley-hackathon`, config
  `dev`, secret `OPENROUTER_API_KEY`).

## Setup

```bash
# 1. Python env (uv) — symlinked as .venv per this repo's convention
uv venv ~/env/recall --python 3.13
ln -s ~/env/recall .venv
uv pip install --python .venv/bin/python -e .

# 2. Frontend deps
cd poc_demo/web && pnpm install && cd ../..
```

All commands below assume the repo root and the `.venv`. Secrets are injected by
`doppler run` — nothing is stored in the repo.

## Run the pipeline (CLI)

```bash
# ingest -> episodes -> load -> show, in one shot (small load by default)
doppler run --project berkeley-hackathon --config dev -- \
  recall all --top-n 5 --limit 150

# or step by step:
recall ingest --top-n 5            # chat.db -> data/events.jsonl   (no key needed)
recall episodes                    # -> data/episodes.jsonl         (no key needed)
doppler run --project berkeley-hackathon --config dev -- \
  recall load --bank imessage-v0 --limit 150   # -> Hindsight (uses OpenRouter)
doppler run --project berkeley-hackathon --config dev -- \
  recall show --bank imessage-v0               # prints the 5 memory networks
```

`recall load` is the only step that costs OpenRouter calls (one LLM extraction
per episode). `--limit` caps how many episodes load; `--limit 0` loads all.

## Run the web demo

Two terminals from the repo root:

```bash
# terminal 1 — backend (boots embedded Hindsight + serves JSON on :8000)
doppler run --project berkeley-hackathon --config dev -- \
  .venv/bin/python -m uvicorn poc_demo.server.app:app --port 8000

# terminal 2 — frontend
cd poc_demo/web && pnpm dev
```

Open **http://localhost:5173**. Wait a few seconds on first load — the backend
runs a live `reflect` through OpenRouter to synthesize the connection panel.

The page shows: the **Hindsight connection** (synthesized cross-conversation
insight), then **Episodic**, **Semantic**, **People**, and **Principles** cards.
The Principles card stays empty until enough episodes are loaded for Hindsight's
consolidation to form mental models — load more with `recall load --limit 0`.

See `poc_demo/README.md` for the API endpoints.

## What's inside

| Path | What |
|---|---|
| `src/recall/ingest.py` | read `chat.db` (read-only) → canonical events |
| `src/recall/episodes.py` | temporal-window events into conversation episodes |
| `src/recall/load.py` | load episodes into Hindsight (retain) |
| `src/recall/show.py` | query the four memory networks + reflect |
| `src/recall/hindsight_runtime.py` | boot embedded Hindsight (pg0 + OpenRouter) |
| `src/recall/cli.py` | `recall ingest\|episodes\|load\|show\|all` |
| `poc_demo/server/` | FastAPI backend for the web UI |
| `poc_demo/web/` | Vite + React + TypeScript frontend |

## Principle trace-back and explanation (backend)

A read path that takes a principle id, walks its provenance, and returns an
LLM explanation of why the principle was inferred. It reads the materialised
graph in SQLite and never writes to it.

```
principle -> principle_memories -> memories -> memory_events -> events (raw)
```

```bash
# list principle ids in the sample DB (no key needed)
PYTHONPATH=src .venv/bin/python -m cli explain

# trace one principle and explain it (uses OpenRouter, so run under Doppler)
doppler run --project berkeley-hackathon --config dev -- \
  env PYTHONPATH=src .venv/bin/python -m cli explain <principle_id>

# rebuild the sample DB if the handoff arrived as JSON
.venv/bin/python scripts/load_sample_json.py <path-to-derek_sample.json>
```

Files: `src/storage/trace.py` (the trace), `src/pipeline/explain.py` (the
agent), the `explain` subcommand in `src/cli.py`, and the design doc in
`docs/principle-traceback-agent.md`.

### Production hardening checklist

What a backend engineer would check to take this from a working POC to
something safe to run on real data. Items already handled in this branch are
marked done; the rest are deliberate follow-ups, not omissions to hide.

**Correctness and data integrity**
- Read-only access. `open_db` opens the DB with `mode=ro`, so the path cannot
  mutate the graph and a wrong `--db` fails loudly instead of creating an empty
  file. (done)
- Defensive shaping. Duplicate join rows are deduped per memory, null
  confidence is coerced, memories with no events still appear, and an unknown
  id returns `None`. (done)
- Schema as a contract. The SQL hardcodes table and column names from
  `SCHEMA.md`. Add a startup check that the expected tables and columns exist
  and fail fast with a clear message if the DB drifts. (follow-up)
- Referential integrity. The trace assumes join ids resolve. Run an orphan
  check (the pattern in Derek's `verify_sample.py`) in CI so a broken export is
  caught before it reaches the read path. (follow-up)

**Testing**
- Offline unit tests with an in-memory fixture DB cover dedupe, null
  confidence, read-only, not-found, and the agent assembly with a fake LLM. 12
  tests, full suite green, ruff clean. (done)
- Add an integration test that builds the sample DB with `load_sample_json.py`
  and traces a real principle, so the loader and the schema are exercised end
  to end. (follow-up)
- Add a contract test that asserts the live schema matches what the SQL
  expects, separate from the fixtures. (follow-up)

**Error handling and resilience**
- LLM failures degrade rather than crash: `LLMWhyExplainer.explain` logs and
  returns an empty string, and the CLI prints a clear message. (done)
- Add a request timeout on the OpenRouter client, plus retry with backoff for
  transient errors, and distinguish transient from permanent failures.
  (follow-up)
- Validate the principle id format before querying. (follow-up)

**Performance and scalability**
- Single query, no N+1: the whole ladder is one `JOIN`, grouped in Python.
  (done)
- Indexes. On `recall.db` (153k events) the join needs indexes on
  `principle_memories(principle_id)`, `memory_events(memory_id)`, and the
  `memories`/`events` primary keys. Confirm they exist or add them; the sample
  DB is small enough to hide a missing index. (follow-up)
- Caching. The trace is cheap and deterministic; the `why` text is the
  expensive, variable part. It can be cached keyed by `principle_id`, which is a
  content hash (see `_principle_id` in `mint.py`), so the cache self-invalidates
  when a principle is reminted. A `CachingWhyExplainer` wrapping the existing
  `WhyExplainer` protocol fits without changing `explain_principle`. Note that
  `open_db` is read-only, so the cache needs its own writable store.
  (follow-up)

**Observability**
- The agent logs failures via loguru. (partial)
- Add structured logs and metrics per call: principle id, memory and event
  counts, latency, model, token usage, estimated cost, and cache hit or miss.
  (follow-up)

**Security and privacy**
- No secrets in the repo. The key is read from the environment that Doppler
  fills in, never hardcoded. (done)
- PII egress. `render_evidence` sends raw message content to OpenRouter. The
  project's privacy stance (CLAUDE.md §7) is abstraction-only egress with remote
  inference in this build. Decide whether raw events should be redacted or
  summarised before they leave the machine, or run a local model. (follow-up,
  important)
- Prompt injection. Raw message text is untrusted input placed in the prompt;
  a message could contain instructions to the model. Harden the system prompt,
  keep evidence clearly delimited, and do not let the model's output trigger
  actions. (follow-up, important)

**If exposed over HTTP**
- A `GET /principles/{id}/why` endpoint in `poc_demo/server` would return
  `to_dict(trace)` plus `why`, 404 when the function returns `None`, one
  connection per request (read-only), input validation, and rate limiting.
  Pagination is not needed at this scale. (follow-up)

**Configuration and cost**
- Model id, temperature, DB path, and timeouts should be configurable rather
  than living as defaults in code; the OpenRouter budget is shared, so add a
  cost guard and cap concurrency. (follow-up)

**CI**
- Run ruff, ty, and pytest on every change, plus the schema and orphan checks
  above, so drift and broken provenance fail in CI rather than at runtime.
  (follow-up)

## Notes

- `chat.db` is read **read-only**; the pipeline never writes to your Messages.
- Loaded data lives in an embedded Postgres (`pg0`) on disk and persists between
  runs, scoped to the bank id (default `imessage-v0`).
- Tests: `.venv/bin/python -m pytest -q` (no network, uses fixtures).
