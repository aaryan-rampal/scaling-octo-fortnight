# RETURN — Hackathon Progress

## Aaryan
- [14:42 PT] Set up Doppler (project: berkeley-hackathon, config: dev) for team-wide OPENROUTER_API_KEY sharing; connected repo aaryan-rampal/scaling-octo-fortnight to GitHub and pushed skills + current.md; added teammates drkchu, selinmutlu06, n1sak with write access after pulling GitHub usernames from team Slack DM; set up Slack MCP server for Claude Code; researched Hindsight (vectorize-io/hindsight) — confirmed it runs as an HTTP service on :8888 with embedded Postgres (pg0, no Docker needed), already wired to OpenRouter in hindsight-setup; pivoted plan to run Hindsight fully self-contained inside recall/ in a git worktree; explored Docker + Colima setup on external SSD (Samsung Extreme SSD, exFAT) for VM storage; now actively testing Hindsight integration

## Derek
- [18:56 PT] Built the capsule write-path + durable SQLite store on the `capsule-ingest` branch (committed `4f6dcc9`).
  - Active path: `POST/GET /api/capsules` persists user-created capsules (place + lat/lng + media: photo/audio/video/text) to SQLite, files saved to disk. Mood left to be derived downstream.
  - Passive path: wired `recall ingest` into the same durable store (`events` table) — iMessage now persists with full traceability: each event keeps `content` + `raw_ref` (chat.db#ROWID) + a `content_sha` provenance hash, plus `verify_event()` to prove a finding's source is untampered even without chat.db.
  - Named it `Capsule` (distinct from Aaryan's flywheel `TimeCapsule`).
  - Added `docs/api-contract.md` for whoever wires the frontend, a standalone visual tester at `localhost:8000/`, and 60 passing tests (ruff clean).
  - Not done (left as seams): capsule→Event→Hindsight retain, principle alignment/swarm, Spotify/LLM connectors (storage is ready).

## Nisa

## Selin
