/* recapsule — seeded demo data, grounded in REAL photo GPS + timestamps.
 *
 * Every capsule below sits at the actual coordinates its photo was taken at
 * (read from EXIF), on the real Cal Hacks timeline (Sat Jun 20, 2026, Berkeley
 * Southside). Place names are reverse-geocoded (Nominatim). The iMessage /
 * Spotify cues are the seeded "fake the ingestion, perfect the insight" layer.
 *
 *   places  → capsules (rich, AI-reconstructed memories)
 *   map     → points of interest with real {lat,lng}; discovered=false → locked
 *   moods   → valence/arousal palette (circumplex)
 *   principles / principleEdges → the principle graph (stage 06)
 */
const ICONS = {
  bed: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16"/><path d="M2 8h18a2 2 0 0 1 2 2v10"/><path d="M2 17h20"/><path d="M6 8v9"/></svg>',
  coffee: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/><line x1="6" y1="2" x2="6" y2="4"/><line x1="10" y1="2" x2="10" y2="4"/><line x1="14" y1="2" x2="14" y2="4"/></svg>',
  stage: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20h20"/><path d="M4 20V8l8-5 8 5v12"/><path d="M9 20v-6h6v6"/></svg>',
  build: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2-2 2.6-2.6Z"/></svg>',
  tower: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 22V8l3-5 3 5v14"/><path d="M9 12h6"/><path d="M7 22h10"/></svg>',
  tree: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22v-7"/><path d="M9 9a3 3 0 1 1 6 0"/><path d="M7 13a4 4 0 1 1 10 0"/><path d="M5.5 17h13"/></svg>',
};

/* Capsules are created by the user (no hardcoded demo data). The app starts
   empty; hydrateFromBackend() fills `places` and `map` from real capsules the
   user creates via the backend. Mood was removed as a capture field. */
const SEED = {
  places: [],        // capsules — populated from created capsules
  map: [],           // map pins — one per created capsule that has coordinates
  covers: [],        // cover shortcuts removed; the uploaded photo is the cover
  principles: [],    // principle graph — empty until real principles exist
  principleEdges: [],
};
