# Enrichment phase — interface contract

Four enrichments improve the memory bank's quality **before** principle-minting
(rung ③/④). Built by parallel teammates on disjoint files; this is the shared
contract. After all land, the lead does ONE live re-retain of the 7-day slice
into a fresh bank and refreshes `data/bank_snapshot.json` + the viewer.

Decided (do not relitigate): cross-source stays at the principle/edge layer
(memories stay single-source); bank is "mostly clean" (the ≥2-memory rule prunes
isolated false positives); names stored plainly (single-user personal data).

Run python via `PYTHONPATH=src .venv/bin/python` (package NOT installed). Lint with
`.venv/bin/ruff check --fix` + `.venv/bin/ruff format` (they autofix). Python 3.13,
≤100 lines/func, absolute imports, Google docstrings, line length 100. Tests
fixtures-only, no network.

## The motivating problems (from real data)
- iMessage threads are keyed by **phone/email handle** (`+16046526819`), so the
  LLM extracts vague "user's friend" and invents name typos ("Marleif" for a real
  contact). The names exist in the **macOS Contacts DB**, unused.
- Photo memories are useless: raw photo rows are `{lat,lng,filename}` with no
  people/caption, so every memory is "took a photo at coordinates X."
- Spotify clustering is polluted by artist names; "listened to X" is shallow.
- Casual slang is misread literally: raw "Brother" (meaning *bro*) →
  "The user has a brother" (a fabricated kinship fact).

---

## Track A — contacts-name join (teammate: `enrich-contacts`)
**Owns:** `src/adapters/imessage.py` + its tests. Do NOT touch other adapters.

- Read the macOS Contacts DB **read-only** (immutable mode, like `photos.py`):
  `~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb`.
  Join `ZABCDRECORD` (ZFIRSTNAME/ZLASTNAME) ↔ `ZABCDPHONENUMBER.ZFULLNUMBER`
  (ZOWNER=record). Also handle email handles if an email-address table exists.
- Build a `handle → contact name` map. Normalize phone numbers for matching
  (strip spaces/`+`/punctuation; match on trailing digits) since `chat.db`
  handles (`+16046526819`) and Contacts (`+1 604 652 6819`) format differently.
- Inject the resolved name into the iMessage adapter output so the rendered text
  / event carries the name (e.g. set a display name on the event, or a
  `contact_name` in `additional_data`) — the renderer (Track shared) will surface
  it. Unknown handles → keep the handle (or "unknown contact"), never a wrong name.
- This fixes BOTH "user's friend" → real name AND the typo (LLM anchors on the
  canonical name). Cross-source entity canonicalization stays OUT of scope — this
  is within-source handle→name only.

**Output:** report the handle→name coverage on the real chat.db (how many of the
slice's threads resolved). Privacy: names are stored plainly per decision.

## Track B — photo vision enrichment (teammate: `enrich-photos`)
**Owns:** `src/adapters/photos.py` + `src/models/photo.py` + their tests.

- Add a preprocessing step: for a photo, call a **cheap OpenRouter vision model**
  on the image → short description + tags. Put them in the photo's
  `additional_data` (`vision_description`, `vision_tags`) so the renderer can use
  them instead of bare coordinates.
- Use the embedded-runtime OpenRouter key path (Doppler injects it); model choice
  is a vision-capable OpenRouter model — pick a cheap one, make it configurable.
- The image binary is on disk at the photo's `original_path` — read it only to
  send to the model; do not copy/persist binaries (repo rule).
- **Guard cost:** make the vision call optional/lazy and cache by photo id, since
  there are thousands of photos library-wide (the slice has ~18). For v0, only
  enrich photos that will actually be retained.

**Output:** sample before/after (coords-only vs description+tags) on a few real
slice photos.

## Track C — spotify artist vibe-cache (teammate: `enrich-spotify`)
**Owns:** `src/adapters/spotify.py` + `src/models/spotify.py` + their tests, plus
a cache file under `data/` (e.g. `data/artist_vibes.json`).

- For each **unique** artist in the spotify events, one cached LLM call (gemini
  via OpenRouter) → a short "vibe" string ("high-energy EDM/pop"). Cache to
  `data/artist_vibes.json` keyed by artist; never re-call a cached artist.
- Surface the vibe in the spotify event/render so a memory reads "listened to
  Calvin Harris (high-energy EDM/pop)" instead of a bare track list.
- Down-weighting artists in clustering is a rung-③ concern, NOT yours — just emit
  the vibe; note it in your report for the minting build.

**Output:** the artist→vibe cache for the slice's artists; sample enriched render.

## Track D — extraction slang-fix (teammate: `enrich-retain-prompt`)
**Owns:** `src/runtime/hindsight.py` ONLY (the retain config), + a small test.

- Hindsight exposes `retain_custom_instructions` (config knob). Set it via our
  runtime env so the extraction prompt instructs: do not infer literal
  relationships/facts from casual slang or terms of endearment ("bro", "brother",
  "bestie", "fam" ≠ literal kinship) — only assert a relationship when the text
  states it literally.
- Find the env var name in the Hindsight slim source
  (`hindsight_api/config.py`, near `retain_custom_instructions`) and set it in
  `_apply_openrouter_env`. Do NOT change the model or embedding config (another
  decision, already set: gemini-3.5-flash + qwen@2000 litellm-sdk).

**Output:** the exact env var + instruction string you set; note it can only be
validated at the live re-retain (lead will check the "brother" case is gone).

---

## Integration (lead, after teammates return)
1. Review each; check disjoint files; run full `pytest -q`.
2. The shared **renderer** (`src/pipeline/render.py`) may need a small update to
   surface contact names / vision text / artist vibes — lead owns that seam to
   avoid 4 teammates editing one file. Teammates put their data in the Event /
   additional_data; lead wires render.
3. ONE live re-retain of the 7-day slice into a fresh bank; refresh
   `data/bank_snapshot.json`; eyeball before/after with `scripts/show_bank.py`.
4. Verify: "user's friend" → names; photos have descriptions; spotify has vibes;
   the "user has a brother" false positive is gone.
