/* RETURN — seeded demo data.
 *
 * "Fake the ingestion, perfect the insight" (architecture doc). Everything here
 * stands in for real pipeline output so the frontend has a live, end-to-end loop.
 * To wire a real backend: replace SEED with a fetch() returning the same shape.
 *
 *   places  → rich AI-reconstructed memories (seeded capsules)
 *   map     → the explorable world: points of interest with x/y % coords.
 *             discovered=false → fogged (visit to unlock). capsuleId → links a capsule.
 *   moods   → valence/arousal palette (circumplex model, arch. stage 03)
 */
const ICONS = {
  tree: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22v-7"/><path d="M9 9a3 3 0 1 1 6 0"/><path d="M7 13a4 4 0 1 1 10 0"/><path d="M5.5 17h13"/></svg>',
  landmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="22" x2="21" y2="22"/><line x1="6" y1="18" x2="6" y2="11"/><line x1="10" y1="18" x2="10" y2="11"/><line x1="14" y1="18" x2="14" y2="11"/><line x1="18" y1="18" x2="18" y2="11"/><polygon points="12 2 20 7 4 7"/></svg>',
  mountain: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="m8 3 4 8 5-5 5 14H2L8 3z"/></svg>',
  coffee: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/><line x1="6" y1="2" x2="6" y2="4"/><line x1="10" y1="2" x2="10" y2="4"/><line x1="14" y1="2" x2="14" y2="4"/></svg>',
};

const SEED = {
  places: [
    {
      id: "moffitt",
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>',
      name: "Moffitt Library",
      place: "UC Berkeley",
      visits: "returned 11 times",
      sealed: true,
      mood: { label: "depleted but driven", hue: 18 },
      cover: "center/cover url('photos/img_2316.jpg')",
      anchor: {
        place: "Moffitt Library, 4th floor",
        time: "Thu Apr 17, 2026 · 2:14 AM",
        photo: "center/cover url('photos/img_2298.jpg')",
      },
      cues: [
        { type: "photo · EXIF", text: "Laptop, dim room. GPS pins the 4th-floor stacks.", time: "02:14 AM" },
        { type: "imessage · Maya", text: "“i don't think i can do this”", time: "02:09 AM" },
        { type: "spotify", text: "on repeat: Phoebe Bridgers — “Funeral” (low energy, sad-valence)", time: "02:11 AM" },
        { type: "note", text: "“one more week.”", time: "02:30 AM" },
        { type: "calendar", text: "CS 61B midterm — today", time: "Apr 17" },
      ],
      storyline:
        "The night before your midterm, you told Maya you couldn't{0}, then wrote *one more week*{1}. You stayed{2}.",
      citations: [
        { n: 1, label: "iMessage · Maya · 2:09 AM" },
        { n: 2, label: "note · 2:30 AM" },
        { n: 3, label: "photo · 2:14 AM" },
      ],
      principle: "I out-wait my own panic by about a week.",
      sealDate: "sealed Apr 17, 2026 · 2:14 AM",
      opener: "are you still scared of it, or just used to it?",
      replies: [
        { match: ["scared", "afraid", "fear"], text: "Of course I'm scared. I just figured out the panic always lifts if I give it one more week. That's the only trick I have." },
        { match: ["maya"], text: "I almost let her talk me out of staying. Telling her “i can't” was me trying to hear myself say it out loud." },
        { match: ["quit", "give up", "bail", "leave"], text: "I wanted to. I wrote “one more week” instead of “I'm done.” Past me always negotiates for a week." },
        { match: ["sleep", "tired", "2am", "late"], text: "2am, no sleep, midterm in hours. The room was so quiet I could hear myself deciding." },
        { match: ["worth", "regret", "glad"], text: "Ask me when grades are out. Right now “worth it” isn't the question — staying is." },
      ],
      fallback: "I only know what I knew that night. Ask me about the midterm, Maya, or why I didn't quit.",
      reflection: "You out-waited the panic again. What's one thing you'd want to carry into the next hard week?",
    },
    {
      id: "marina",
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/></svg>',
      name: "Berkeley Marina",
      place: "south path",
      visits: "returned 6 times",
      sealed: false,
      mood: { label: "wistful, searching", hue: 205 },
      cover: "center/cover url('photos/img_2303.jpg')",
      anchor: {
        place: "Berkeley Marina, south path",
        time: "Sun Feb 9, 2026 · 6:48 PM",
        photo: "center/cover url('photos/img_2303.jpg')",
      },
      cues: [
        { type: "photo · EXIF", text: "Sunset over the bay, alone.", time: "06:48 PM" },
        { type: "spotify", text: "playing: Bon Iver — “Holocene” (mid-arousal, melancholic)", time: "06:49 PM" },
        { type: "voice note", text: "“maybe i took the internship for the wrong reason.” (low, slow)", time: "06:51 PM" },
        { type: "imessage · Dad", text: "“proud of you kiddo”", time: "05:30 PM" },
      ],
      storyline:
        "You came to the water alone after Dad said he was proud{0}, and said out loud the thing you couldn't text back{1}: maybe it was the wrong reason.",
      citations: [
        { n: 1, label: "iMessage · Dad · 5:30 PM" },
        { n: 2, label: "voice note · 6:51 PM" },
      ],
      principle: "I go to the water to say the things I can't say to people.",
      sealDate: "sealed Feb 9, 2026 · 6:48 PM",
      opener: "did you ever tell him what you really thought?",
      replies: [
        { match: ["dad", "father", "him"], text: "No. “Proud of you” landed wrong and I couldn't explain why without sounding ungrateful." },
        { match: ["internship", "job", "work", "reason"], text: "I think I took it to make someone else's face do that. The water made that obvious." },
        { match: ["wrong", "regret", "mistake"], text: "Not wrong exactly. Wrong reason. There's a difference I was just starting to feel." },
      ],
      fallback: "That evening I was mostly quiet. Ask me about Dad, the internship, or the wrong reason.",
      reflection: "You named the wrong reason out loud. What would a right reason look like, going forward?",
    },
  ],

  // the explorable world — % coordinates within the map
  map: [
    { id: "marina",     name: "Berkeley Marina", x: 19, y: 78, discovered: true,  capsuleId: "marina" },
    { id: "moffitt",    name: "Moffitt Library", x: 38, y: 50, discovered: true,  capsuleId: "moffitt" },
    { id: "glade",      name: "Memorial Glade",  x: 66, y: 38, discovered: true,  icon: ICONS.tree },
    { id: "campanile",  name: "The Campanile",   x: 60, y: 64, discovered: true,  icon: ICONS.landmark },
    { id: "indianrock", name: "Indian Rock",     x: 82, y: 18, discovered: false, icon: ICONS.mountain },
    { id: "gourmet",    name: "Gourmet Ghetto",  x: 24, y: 24, discovered: false, icon: ICONS.coffee },
  ],

  // mood palette for sealing a new capsule (valence/arousal)
  moods: [
    { label: "calm",    hue: 158 },
    { label: "hopeful", hue: 45 },
    { label: "proud",   hue: 32 },
    { label: "wistful", hue: 205 },
    { label: "heavy",   hue: 255 },
    { label: "anxious", hue: 8 },
  ],

  // cover gradients to choose from when sealing a capsule
  covers: [
    "linear-gradient(150deg,#3a2c1f 0%,#6b4a2c 55%,#c8743c 120%)",
    "linear-gradient(150deg,#1f2a33 0%,#37505e 55%,#c8743c 135%)",
    "linear-gradient(150deg,#2a2140 0%,#4a3a5e 55%,#cf7f86 130%)",
    "linear-gradient(150deg,#1f3329 0%,#3a5e4a 55%,#e8c188 135%)",
  ],

  // principle graph (architecture stage 06): principle nodes, the capsules that
  // formed them, and typed alignment/contradiction edges between principles.
  principles: [
    { id: "p1", label: "Out-wait the panic", text: "I out-wait my own panic by about a week.", capsules: ["moffitt"] },
    { id: "p2", label: "Say it only alone", text: "I say the hard things only when I'm alone.", capsules: ["marina"] },
    { id: "p3", label: "Achieve, even at a cost", text: "I chase achievement even when it costs me peace.", capsules: ["moffitt", "marina"] },
  ],
  principleEdges: [
    { a: "p1", b: "p3", type: "align" },      // out-waiting panic serves achievement
    { a: "p2", b: "p3", type: "contradict" }, // needing solitude vs. always pushing
  ],
};
