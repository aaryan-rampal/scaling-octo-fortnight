# RETURN — UI

The frontend scaffold for the live demo: the **reconstruct-before-reveal** loop
from `context/RETURN-architecture.pdf`. Zero build, no dependencies — just open it.

## Run it

```bash
# from repo root
cd ui

# option A — just open the file
open index.html

# option B — serve it (better for phone testing on the same wifi)
python3 -m http.server 5173
# then visit http://localhost:5173  (or http://<your-laptop-ip>:5173 on your phone)
```

## The demo loop

1. **Places** — stands in for geofence triggers. Tap a place you've "returned" to
   (the *I'm back* button = the FAKE geofence from the build plan).
2. **Reconstruct** — the photo anchor, then co-temporal cues stream in one by one
   (cross-source fusion, architecture stage 02). This is the "reconstruct before
   reveal" beat.
3. **Reveal** — the grounded storyline with inline citation chips (stage 08:
   every clause points at the event it came from).
4. **Talk to past you** — chat with the version of you sealed at that moment
   (stage 09). Ask it about that night; it only knows what it knew then.

## Wiring the real backend

All seeded data lives in `seed.js`. `app.js` reads it through `getPlaces()` /
`getPlace()` only — swap those two functions for `fetch()` calls returning the
same shape and the UI is live against the real pipeline. Nothing else changes.

## Files

| file | what |
|------|------|
| `index.html` | markup + the three views |
| `styles.css` | warm/dark theme matching the architecture deck |
| `seed.js` | demo data (the Moffitt / Maya worked trace + one more) |
| `app.js` | view routing, the staged reconstruct, persona chat |
