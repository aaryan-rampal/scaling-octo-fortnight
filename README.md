recapsule

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

## The local-first capsule app (`recall serve`)

Run the whole app — UI, API, and media — from one command, all on your machine.
Your photos, notes, and memories never leave the device; the server just reads
and writes local SQLite + files.

```bash
# laptop-only (safest): nothing on the network can reach it
recall serve --host 127.0.0.1

# open http://localhost:8000
```

Create a time capsule in the UI (a place + photos + a note). It persists to the
local SQLite store **and** is projected into the unified `events` table as a
canonical `Event` (`source="capsule"`) — the same provenance path as the passive
sources (iMessage / Spotify / photos), ready to rise into memory.

### Reach it from your phone (data stays on your laptop)

The phone talks to *your laptop*; the data is never uploaded to a cloud. Protect
it with a passcode first — required whenever you expose the port:

```bash
recall serve --token "your-passcode"        # gates API + media behind the passcode
# (or set RECALL_TOKEN in the env)
```

Then make the laptop reachable from the phone. Two options:

**Same wifi (simplest):**
```bash
recall serve --host 0.0.0.0 --token "your-passcode"
# phone (same wifi): http://<your-laptop-ip>:8000   (mac: ipconfig getifaddr en0)
```

**From anywhere, privately (recommended): Tailscale**
A private encrypted network between *your own devices* — the laptop is never
exposed to the public internet.
```bash
# install Tailscale on the laptop AND the phone, then on the laptop:
tailscale up
recall serve --host 0.0.0.0 --token "your-passcode"
# phone: http://<laptop-tailscale-ip>:8000
```

**Quick public URL (demo): ngrok**
```bash
recall serve --token "your-passcode"
ngrok http 8000          # open the https URL it prints on your phone
```
The passcode is what protects the tunnel — anyone with the URL still needs it.

On first load the UI shows a passcode lock screen (styled to match the app);
enter the passcode once and the device stays unlocked. Memory networks
(`/api/networks`) need OpenRouter and are skipped gracefully if no key is
configured — capsule creation, media, and listing work without it.
