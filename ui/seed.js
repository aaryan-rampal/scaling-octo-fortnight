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

const SEED = {
  places: [
    {
      id: "durant",
      icon: ICONS.bed,
      name: "The room on Durant",
      place: "Durant Ave",
      visits: "8:15 AM · where you woke up",
      sealed: true,
      mood: { label: "quiet, bracing", hue: 32 },
      music: "Clairo — Bags",
      media: [{ type: "photo", src: "photos/img_2298.jpg" }],
      cover: "center/cover url('photos/img_2298.jpg')",
      anchor: { place: "Durant Ave · Southside", time: "Sat Jun 20, 2026 · 8:15 AM", photo: "center/cover url('photos/img_2298.jpg')" },
      cues: [
        { type: "photo · EXIF", text: "Curtains half-open, bed unmade. GPS: 37.8678, -122.2562.", time: "08:15 AM" },
        { type: "spotify", text: "low volume: Clairo — “Bags” (calm, sad-valence)", time: "08:12 AM" },
        { type: "imessage · team", text: "“we actually doing this 😅”", time: "08:05 AM" },
      ],
      storyline:
        "The morning of, in a half-dark room on Durant{0}, you answered the team before you'd decided you were ready{1}.",
      citations: [
        { n: 1, label: "photo · 8:15 AM · Durant Ave" },
        { n: 2, label: "iMessage · team · 8:05 AM" },
      ],
      principle: "I show up before I feel ready.",
      sealDate: "sealed Jun 20, 2026 · 8:15 AM",
      opener: "be honest — did you think we could pull it off?",
      replies: [
        { match: ["ready", "scared", "nervous"], text: "Not even close to ready. I said yes anyway and figured the readiness would catch up." },
        { match: ["sleep", "tired"], text: "Barely slept. The room was too quiet and my head was too loud." },
        { match: ["team", "win", "pull"], text: "I didn't know if we'd pull it off. I knew I'd rather try with them than not." },
      ],
      fallback: "It's 8am and I haven't had coffee. Ask me about the team, the nerves, or the no-sleep.",
      reflection: "You showed up unsure and started anyway. What's the next thing you're not-ready-for?",
    },
    {
      id: "telegraph",
      icon: ICONS.coffee,
      name: "Quargo Coffee",
      place: "Telegraph Ave",
      visits: "8:53 AM · before the doors",
      sealed: false,
      mood: { label: "caffeine optimism", hue: 45 },
      music: "Still Woozy — Goodie Bag",
      media: [{ type: "photo", src: "photos/img_2303.jpg" }],
      cover: "center/cover url('photos/img_2303.jpg')",
      anchor: { place: "Telegraph Ave · Southside", time: "Sat Jun 20, 2026 · 8:53 AM", photo: "center/cover url('photos/img_2303.jpg')" },
      cues: [
        { type: "photo · EXIF", text: "Empty Telegraph, fog not burned off yet. 37.8679, -122.2590.", time: "08:53 AM" },
        { type: "spotify", text: "playing: Still Woozy — “Goodie Bag” (bright, mid-arousal)", time: "08:55 AM" },
        { type: "imessage · Nisa", text: "“matcha first, obviously”", time: "08:48 AM" },
      ],
      storyline:
        "You walked a quiet Telegraph for coffee{0} — the last calm before twenty-four hours of noise.",
      citations: [{ n: 1, label: "photo · 8:53 AM · Telegraph Ave" }],
      principle: "Caffeine is my courage.",
      sealDate: "sealed Jun 20, 2026 · 8:53 AM",
      opener: "what were you most looking forward to?",
      replies: [
        { match: ["matcha", "coffee", "drink"], text: "Matcha, then coffee, then probably more coffee. Fuel for the whole thing." },
        { match: ["nervous", "scared", "ready"], text: "Less nervous with a warm cup in my hand. That's the trick." },
      ],
      fallback: "Quiet street, warm cup. Ask me about the morning or the matcha run.",
      reflection: "The calm before counted too. What small ritual do you want to keep for next time?",
    },
    {
      id: "ceremony",
      icon: ICONS.stage,
      name: "Opening ceremony",
      place: "South Drive",
      visits: "10:10 AM · lights down",
      sealed: false,
      mood: { label: "small in a big room", hue: 265 },
      music: "(opening ceremony — no music)",
      media: [{ type: "photo", src: "photos/img_2311.jpg" }, { type: "photo", src: "photos/img_2316.jpg" }],
      cover: "center/cover url('photos/img_2316.jpg')",
      anchor: { place: "South Drive · UC Berkeley", time: "Sat Jun 20, 2026 · 10:10 AM", photo: "center/cover url('photos/img_2311.jpg')" },
      cues: [
        { type: "photo · EXIF", text: "Dark auditorium, “AI 2026” on the screen. 37.8710, -122.2592.", time: "10:10 AM" },
        { type: "slide", text: "“$11.7M raised” — YC, AMD, Hugging Face on the wall", time: "10:18 AM" },
        { type: "imessage · Derek", text: "“where are you sitting”", time: "10:06 AM" },
      ],
      storyline:
        "In the dark before any code{0}, you watched the sponsors' numbers climb{1} and let yourself believe the weekend mattered.",
      citations: [
        { n: 1, label: "photo · 10:10 AM · auditorium" },
        { n: 2, label: "slide · 10:18 AM" },
      ],
      principle: "I dream bigger than I let on.",
      sealDate: "sealed Jun 20, 2026 · 10:10 AM",
      opener: "did the big numbers scare you or excite you?",
      replies: [
        { match: ["scare", "small", "nervous"], text: "Both. The room was huge and I felt tiny, and somehow that made me want it more." },
        { match: ["dream", "win", "believe"], text: "For a second in the dark I let myself believe we'd make something real." },
      ],
      fallback: "Lights are down, screen's glowing. Ask me what I was feeling in that seat.",
      reflection: "You let yourself want it. What would 'it mattered' look like a month from now?",
    },
    {
      id: "venue",
      icon: ICONS.build,
      name: "The build",
      place: "Bancroft Way",
      visits: "1:53 PM · heads down",
      sealed: true,
      mood: { label: "wired, alive", hue: 12 },
      music: "Charli xcx — 365",
      cover: "center/cover url('photos/img_2334.jpg')",
      media: [
        { type: "video", src: "photos/vid_venue.mp4", poster: "photos/vid_venue.jpg" },
        { type: "photo", src: "photos/img_2333.jpg" },
        { type: "photo", src: "photos/img_2334.jpg" },
      ],
      anchor: { place: "Bancroft Way · the venue lawn", time: "Sat Jun 20, 2026 · 1:53 PM", photo: "center/cover url('photos/img_2334.jpg')" },
      cues: [
        { type: "photo · EXIF", text: "Tent full of laptops; a llama on the lawn outside. 37.8692, -122.2595.", time: "01:53 PM" },
        { type: "spotify", text: "on repeat: Charli xcx — “365” (high energy)", time: "02:10 PM" },
        { type: "imessage · team", text: "“there are ROBOTS outside”", time: "03:31 PM" },
      ],
      storyline:
        "Somewhere between the llama and the robots{0}, the four of you stopped planning and started building{1}.",
      citations: [
        { n: 1, label: "photo · 1:53 PM · Bancroft lawn" },
        { n: 2, label: "iMessage · team · 3:31 PM" },
      ],
      principle: "I find my people by making things with them.",
      sealDate: "sealed Jun 20, 2026 · 1:53 PM",
      opener: "when did it start to feel real?",
      replies: [
        { match: ["real", "start", "build"], text: "When we stopped arguing about the plan and someone just opened a laptop. Then it was real." },
        { match: ["team", "people", "four"], text: "Four people, one table. I find people by building next to them." },
        { match: ["robot", "llama", "tired"], text: "There was a llama. There were robots. There was no sleep. Best kind of day." },
      ],
      fallback: "Heads-down at the venue. Ask me about the team, the build, or the robots.",
      reflection: "You found your people by making something. Who do you want to build with next?",
    },
  ],

  // the explorable world — REAL lat/lng from photo EXIF + two locked campus spots
  map: [
    { id: "durant",    name: "The room on Durant", lat: 37.867839, lng: -122.256194, discovered: true, capsuleId: "durant" },
    { id: "telegraph", name: "Quargo Coffee",      lat: 37.867930, lng: -122.259000, discovered: true, capsuleId: "telegraph" },
    { id: "ceremony",  name: "Opening ceremony",   lat: 37.871050, lng: -122.259220, discovered: true, capsuleId: "ceremony" },
    { id: "venue",     name: "The build",          lat: 37.869200, lng: -122.259500, discovered: true, capsuleId: "venue" },
    { id: "campanile", name: "Sather Tower",       lat: 37.872090, lng: -122.257860, discovered: false, icon: ICONS.tower },
    { id: "glade",     name: "Memorial Glade",     lat: 37.873550, lng: -122.258880, discovered: false, icon: ICONS.tree },
  ],

  moods: [
    { label: "calm", hue: 158 }, { label: "hopeful", hue: 45 }, { label: "proud", hue: 32 },
    { label: "wistful", hue: 205 }, { label: "heavy", hue: 255 }, { label: "wired", hue: 12 },
  ],
  covers: [
    "center/cover url('photos/img_2334.jpg')",
    "center/cover url('photos/img_2316.jpg')",
    "center/cover url('photos/img_2303.jpg')",
    "center/cover url('photos/img_2333.jpg')",
  ],

  principles: [
    { id: "p1", label: "Show up before you're ready", text: "I show up before I feel ready.", capsules: ["durant", "ceremony"] },
    { id: "p2", label: "Make things to find people", text: "I find my people by making things with them.", capsules: ["venue", "telegraph"] },
    { id: "p3", label: "Dream bigger than I admit", text: "I dream bigger than I let on.", capsules: ["ceremony", "durant"] },
  ],
  principleEdges: [
    { a: "p1", b: "p3", type: "align" },
    { a: "p2", b: "p3", type: "contradict" },
  ],
};
