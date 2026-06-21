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

## Notes

- `chat.db` is read **read-only**; the pipeline never writes to your Messages.
- Loaded data lives in an embedded Postgres (`pg0`) on disk and persists between
  runs, scoped to the bank id (default `imessage-v0`).
- Tests: `.venv/bin/python -m pytest -q` (no network, uses fixtures).
