# RETURN — Hackathon Progress

## Aaryan

## Derek
- [18:56 PT] Built the capsule write-path + durable SQLite store on the `capsule-ingest` branch (committed `4f6dcc9`).
  - Active path: `POST/GET /api/capsules` persists user-created capsules (place + lat/lng + media: photo/audio/video/text) to SQLite, files saved to disk. Mood left to be derived downstream.
  - Passive path: wired `recall ingest` into the same durable store (`events` table) — iMessage now persists with full traceability: each event keeps `content` + `raw_ref` (chat.db#ROWID) + a `content_sha` provenance hash, plus `verify_event()` to prove a finding's source is untampered even without chat.db.
  - Named it `Capsule` (distinct from Aaryan's flywheel `TimeCapsule`).
  - Added `docs/api-contract.md` for whoever wires the frontend, a standalone visual tester at `localhost:8000/`, and 60 passing tests (ruff clean).
  - Not done (left as seams): capsule→Event→Hindsight retain, principle alignment/swarm, Spotify/LLM connectors (storage is ready).

## Nisa

## Selin
