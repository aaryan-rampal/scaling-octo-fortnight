# RETURN — UI

The **mobile web app** for the live demo: the reconstruct-before-reveal loop
from `context/RETURN-architecture.pdf`. Zero build, no dependencies, no
framework — just static files. On a phone it runs full-screen like a native
app; on a laptop it shows inside a phone frame so the team can preview it.

## 🔗 Live demo (no setup — just open it)

**https://selinmutlu06.github.io/scaling-octo-fortnight/**

Anyone can open that link on a laptop or phone — no install, no clone.

### Open it + edit it + see your edits live
1. Edit any file in `ui/` on the `ui-scaffold` branch.
2. Publish your edits to the live link:
   ```bash
   git push fork ui-scaffold      # `fork` = your GitHub Pages copy
   ```
3. The committed workflow (`.github/workflows/deploy-ui.yml`) redeploys the
   demo automatically (~1 min). Refresh the link.

> The deploy pipeline lives **in this branch**, so the live demo is reproducible
> from the branch alone. When a repo admin enables Pages on the main repo, the
> same workflow deploys from there (remove the `if:` guard in the workflow).

## Run it locally

```bash
# from repo root
cd ui

# laptop preview
open index.html

# test on your actual phone (same wifi) — serve it, then open the URL on your phone
python3 -m http.server 5173
# laptop:  http://localhost:5173
# phone:   http://<your-laptop-ip>:5173   (e.g. 192.168.1.x — run `ipconfig getifaddr en0`)
```

### Make it look like an installed app on your phone
1. Open the served URL in **Safari (iPhone)** or **Chrome (Android)**.
2. Share → **Add to Home Screen**.
3. Launch from the home-screen icon — it opens full-screen, no browser chrome.

(`manifest.json` + the apple meta tags in `index.html` handle this. No service
worker on purpose, so edits show up immediately while we're iterating.)

## The demo loop

1. **Places** — stands in for geofence triggers. Tap a place you've "returned"
   to (the *I'm back* button = the FAKE geofence from the build plan).
2. **Reconstruct** — the photo anchor, then co-temporal cues stream in one by
   one (cross-source fusion, stage 02). The "reconstruct before reveal" beat.
3. **Reveal** — the grounded storyline with inline citation chips (stage 08:
   every clause points at the event it came from).
4. **Talk to past you** — chat with the version of you sealed at that moment
   (stage 09). It only knows what it knew then.

## Editing the UI (start here)

Everyone can edit safely — the three concerns are split into three files:

| file | edit this to change… |
|------|----------------------|
| `seed.js` | **the demo content** — places, photos, cues, storyline, citations, the persona's replies. Pure data, no logic. |
| `styles.css` | **the look** — colors live in the `:root` variables at the top; the desktop phone frame is the `@media (min-width: 600px)` block at the bottom. |
| `index.html` | **the structure** — the three `<section class="view">` blocks. |
| `app.js` | **the behavior** — view routing, the staged reconstruct animation, the persona chat. |

Tips:
- Recolor the whole app by editing the `--accent` / `--bg` / `--ink` variables in `styles.css`.
- Add a new demo place: copy one object in `SEED.places` (`seed.js`) and change the fields.
- No build step — save the file and refresh.

## Wiring the real backend later

`app.js` reads all data through `getPlaces()` / `getPlace()` only. Swap those
two functions for `fetch()` calls that return the same shape as `seed.js` and
the UI is live against the real pipeline. Nothing else changes.

## Files

| file | what |
|------|------|
| `index.html` | markup + the three views + PWA meta tags |
| `styles.css` | theme + responsive (full-screen phone / framed desktop) |
| `seed.js` | demo data (the Moffitt / Maya worked trace + one more) |
| `app.js` | view routing, staged reconstruct, persona chat |
| `manifest.json`, `icon.svg` | make it installable / add-to-home-screen |
