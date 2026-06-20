/* RETURN — seeded demo data.
 *
 * "Fake the ingestion, perfect the insight" (architecture doc). Everything here
 * stands in for real pipeline output so the frontend has a live, end-to-end loop.
 *
 * To wire a real backend: replace SEED with a fetch() returning the same shape.
 * Nothing in app.js assumes this is static.
 *
 * Fields worth knowing:
 *   sealed      → location-locked capsule; needs "I'm back" to open (Nisa's differentiator)
 *   mood        → valence/arousal read (circumplex model, arch. stage 03) — {label, hue}
 *   cues        → co-temporal/co-located events fused into the moment (stage 02)
 *   storyline   → grounded narration; {n} markers map to citations (stage 08)
 *   reflection  → forward-looking closing prompt (Selin's wellbeing guardrail, Q15)
 */
const SEED = {
  places: [
    {
      id: "moffitt",
      // Lucide "book-open" — SVG icon, not an emoji (font-independent, themeable)
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>',
      name: "Moffitt Library",
      place: "UC Berkeley",
      visits: "returned 11 times",
      sealed: true,
      mood: { label: "depleted but driven", hue: 18 },
      cover: "linear-gradient(150deg,#3a2c1f 0%,#6b4a2c 55%,#c8743c 120%)",
      anchor: {
        place: "Moffitt Library, 4th floor",
        time: "Thu Apr 17, 2026 · 2:14 AM",
        photo: "linear-gradient(135deg,#2b2620 0%,#3a3128 45%,#4a3a2a 100%)",
      },
      cues: [
        { type: "photo · EXIF", text: "Laptop, dim room. GPS pins the 4th-floor stacks.", time: "02:14 AM" },
        { type: "imessage · Maya", text: "“i don't think i can do this”", time: "02:09 AM" },
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
      // Lucide "waves"
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 6c.6.5 1.2 1 2.5 1C7 7 7 5 9.5 5c2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 12c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M2 18c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 2.6 0 2.4 2 5 2 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/></svg>',
      name: "Berkeley Marina",
      place: "south path",
      visits: "returned 6 times",
      sealed: false,
      mood: { label: "wistful, searching", hue: 205 },
      cover: "linear-gradient(150deg,#1f2a33 0%,#37505e 55%,#c8743c 135%)",
      anchor: {
        place: "Berkeley Marina, south path",
        time: "Sun Feb 9, 2026 · 6:48 PM",
        photo: "linear-gradient(135deg,#1f2a33 0%,#2b3a44 50%,#c8643c 140%)",
      },
      cues: [
        { type: "photo · EXIF", text: "Sunset over the bay, alone.", time: "06:48 PM" },
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
};
