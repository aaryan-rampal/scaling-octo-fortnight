/* RETURN — seeded demo data.
 *
 * This is the "fake the ingestion, perfect the insight" layer from the
 * architecture doc. Everything here stands in for the real pipeline output
 * so the frontend has a live, end-to-end loop to demo against.
 *
 * To wire a real backend: replace SEED with a fetch() that returns the same
 * shape. Nothing in app.js assumes this is static.
 */
const SEED = {
  places: [
    {
      id: "moffitt",
      emoji: "📚",
      name: "Moffitt Library",
      desc: "UC Berkeley · you've returned here 11 times",
      back: "I'm back",
      // anchor = the photo that opens the capsule
      anchor: {
        place: "Moffitt Library, 4th floor",
        time: "Thu Apr 17, 2026 · 2:14 AM",
        // soft gradient stand-in for the dim-room laptop photo
        photo: "linear-gradient(135deg,#2b2620 0%,#3a3128 45%,#4a3a2a 100%)",
      },
      // staged co-temporal / co-located cues (cross-source fusion, stage 02)
      cues: [
        { type: "photo · EXIF", text: "Laptop, dim room. GPS pins the 4th-floor stacks.", time: "02:14 AM" },
        { type: "imessage · Maya", text: "“i don't think i can do this”", time: "02:09 AM" },
        { type: "note", text: "“one more week.”", time: "02:30 AM" },
        { type: "calendar", text: "CS 61B midterm — today", time: "Apr 17" },
      ],
      // grounded storyline (stage 08). [n] markers map to citations below.
      storyline:
        "The night before your midterm, you told Maya you couldn't{0}, then wrote *one more week*{1}. You stayed{2}.",
      citations: [
        { n: 1, label: "iMessage · Maya · 2:09 AM" },
        { n: 2, label: "note · 2:30 AM" },
        { n: 3, label: "photo · 2:14 AM" },
      ],
      // talk-to-past-you (stage 09): persona sealed at this timestamp
      sealDate: "sealed Apr 17, 2026 · 2:14 AM",
      opener: "are you still scared of it, or just used to it?",
      // tiny rule-based persona so the demo replies even with no backend
      replies: [
        { match: ["scared", "afraid", "fear"], text: "Of course I'm scared. I just figured out the panic always lifts if I give it one more week. That's the only trick I have." },
        { match: ["maya"], text: "I almost let her talk me out of staying. Telling her “i can't” was me trying to hear myself say it out loud." },
        { match: ["quit", "give up", "bail", "leave"], text: "I wanted to. I wrote “one more week” instead of “I'm done.” Past me always negotiates for a week." },
        { match: ["sleep", "tired", "2am", "late"], text: "2am, no sleep, midterm in hours. The room was so quiet I could hear myself deciding." },
        { match: ["worth", "regret", "glad"], text: "Ask me when grades are out. Right now “worth it” isn't the question — staying is." },
      ],
      fallback: "I only know what I knew that night. Ask me about the midterm, Maya, or why I didn't quit.",
    },
    {
      id: "marina",
      emoji: "🌊",
      name: "Berkeley Marina",
      desc: "you've returned here 6 times — mostly to think",
      back: "I'm back",
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
      sealDate: "sealed Feb 9, 2026 · 6:48 PM",
      opener: "did you ever tell him what you really thought?",
      replies: [
        { match: ["dad", "father", "him"], text: "No. “Proud of you” landed wrong and I couldn't explain why without sounding ungrateful." },
        { match: ["internship", "job", "work", "reason"], text: "I think I took it to make someone else's face do that. The water made that obvious." },
        { match: ["wrong", "regret", "mistake"], text: "Not wrong exactly. Wrong reason. There's a difference I was just starting to feel." },
      ],
      fallback: "That evening I was mostly quiet. Ask me about Dad, the internship, or the wrong reason.",
    },
  ],
};
