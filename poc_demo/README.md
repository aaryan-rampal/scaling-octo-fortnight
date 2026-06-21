# Recall — web demo

A small web UI over the iMessage memory pipeline. The FastAPI backend boots
embedded Hindsight (pg0 + OpenRouter) once and serves the five memory networks
as JSON; the Vite/React frontend renders them.

## Run (two terminals)

**1. Backend** (from the repo worktree root, via Doppler for the API key):

```bash
doppler run --project berkeley-hackathon --config dev -- \
  .venv/bin/python -m uvicorn poc_demo.server.app:app --port 8000
```

Wait for `Application startup complete` — that means pg0 booted and the embedded
Hindsight client is ready. Defaults to bank `imessage-v0` (override with
`RECALL_BANK=...`).

**2. Frontend:**

```bash
cd poc_demo/web
pnpm install   # first time only
pnpm dev
```

Open http://localhost:5173. The page fetches `/api/networks` (proxied to the
backend on :8000) and renders:

- **Hindsight connection** — the synthesized cross-conversation insight (the money shot)
- **Episodic memory** — significant experiences with timestamps
- **Semantic memory** — durable world facts
- **People** — extracted entities
- **Principles** — evolving beliefs (empty until enough episodes are loaded)

## Endpoints

- `GET /api/health` — `{status, bank}`
- `GET /api/networks?bank=imessage-v0` — all five networks as JSON

## Notes

- The bank must already be loaded (`recall load --bank imessage-v0`). The UI
  reads whatever is in the bank; it does not ingest.
- Booting the backend takes a few seconds (pg0 + the Hindsight lifespan).
