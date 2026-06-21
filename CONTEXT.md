# recapsule — project context (handoff)

A quick brief to get a teammate up to speed. **recapsule** is our Cal Hacks 2026
project (working name was "RETURN").

## What it is

A location-based **memory time-capsule** app. You explore a map, **seal capsules**
at real places, and they **lock until you return**. When you open one, the app
**reconstructs the moment** from your own data (photos + iMessage + Spotify),
surfaces a one-line **principle** ("I show up before I feel ready"), and lets you
**talk to past you**. Principles connect into a graph you can explore.

One-liner: *return to a moment, not just a place.*

## 🔗 Live demo (open on phone or laptop)

**https://selinmutlu06.github.io/scaling-octo-fortnight/**

## The loop (what the demo shows)

1. **Map** (satellite, hand-drawn styling) — real Cal Hacks locations as pins.
   Tap a locked pin → travel there → it unlocks. Tap a `+` pin → seal a capsule.
2. **Seal a capsule** — mood + note + cover; it locks until you "return."
3. **Open a capsule** — big unearth animation + sound → the reveal page.
4. **Reveal** — grounded storyline with citation chips, the surfaced **principle**,
   a forward-looking **reflection** (wellbeing guardrail), and **talk to past you**.
5. **Graph** (Obsidian-style) — principles + the memories that formed them, with
   alignment / contradiction edges. Tap a principle → its memories light up.

## Capsule data model

Each capsule = `place name · coordinates · time · media (text / photos / video)
· mood (agent-derived) · music played`. See `ui/seed.js` for the exact shape.
The locations + timestamps are **real** (read from photo EXIF GPS); the
iMessage/Spotify cues are seeded stand-ins ("fake the ingestion, perfect the
insight").

## Tech / how to work on it

- **Frontend** lives in `ui/` — zero-build, vanilla **HTML/CSS/JS**, no framework.
  - `index.html` structure · `styles.css` look · `seed.js` all demo data ·
    `app.js` behavior · `photos/` real media.
  - Live satellite map = **MapLibre GL** + Esri World Imagery (no API key).
- **Run locally:** `cd ui && python3 -m http.server 5173` → open `localhost:5173`
  (phone on same wifi: `http://<laptop-ip>:5173`).
- **Edit → deploy:** push branch `ui-scaffold`; a GitHub Action redeploys the
  live link (`.github/workflows/deploy-ui.yml`). See `ui/README.md`.
- **Wire the real backend later:** `app.js` reads everything through
  `getPlaces()` / `getPlace()`. Swap those for `fetch()` returning the same
  shape as `seed.js` and the UI goes live against the pipeline. Nothing else changes.

## What's real vs. faked (be honest in the pitch)

- **Real:** locations + timestamps (photo EXIF), the photos/video, the UI/UX loop.
- **Faked for 24h:** geofencing ("I'm back" button), the iMessage/Spotify ingestion
  (seeded), and the principle extraction is pre-written, not yet live from an LLM.
- The full pipeline (abstraction → principle graph → retrieve/rerank → grounded
  storyline) is specified in `context/RETURN-architecture.pdf` — that's the
  north star; the demo is one focused, real-feeling loop.

## Open decisions (Hour-0 whiteboard)

From `context/team-questions-and-answers.md`, the ones that still matter:
- **Hero beat:** intentional capsule-creation (6/18 consensus, Nisa's location-lock
  differentiator) vs. photo-in reconstruction. The UI now supports **both**.
- **Memory engine:** Hindsight vs. Redis vs. both.
- **Crisis detection** (unowned) + **nostalgia guardrail** (Selin owns; the
  forward-looking reflection is the first mechanic).
- **Voice** as a core interaction → Deepgram prize + strengthens "talk to past you".

## Status / next steps

- Done: full front-end demo loop, real locations, satellite map, principle graph,
  capsule create/open, sounds, multi-source reconstruct, talk-to-past-you.
- Next: wire real abstraction/principle extraction (Claude), real retrieval,
  optional voice (Deepgram), and decide the memory engine.
