# RETURN — Combined Team Q&A (v2): Decisions We Owe Each Other

*Synthesized from all working docs, every one treated as canonical. New since v1: the **6/18 four-person team huddle** — the only artifact with all four of us, and it postdates the design docs. It changes several answers and one of my earlier conclusions (see §0).*

**Team:** Aaryan, Derek, Nisa, Selin. The Nisa/Selin "no position on record" gap from v1 is now **largely closed** — both shaped the 6/18 meeting. Where input is still genuinely missing, it's marked **[GAP]**.

**Source chronology (this matters — later supersedes earlier):**

- **6/14** — Aaryan + Derek 1:1 huddle (`transcript.md`, `slack_summary…md`, and the now-duplicated `team_transcript.md`). Product = journal/situation-in principles tracker.
- **6/16** — `Design Doc v0.docx` (Aaryan), `design-doc.docx` (Derek), `unified-design-doc-v2.docx`. Still journal/situation-in.
- **6/18** — **four-person team huddle** (`team_trasncript_2.md`). **Pivot to location-based time capsules + photos + nostalgia, hybrid passive/intentional.** This is the real team consensus.
- **6/20 (today)** — `RETURN-architecture.pdf`. Engineering elaboration of the 6/18 direction.

---

## 0. Read this first — including a correction

**The hackathon is now.** Today is Saturday, June 20; Cal Hacks is Jun 20–21. The 6/18 meeting explicitly chose **no further pre-hackathon meetings** — everything is resolved offline via Slack or in the **30–40 min whiteboard at the start**. So the questions below are Hour-0 whiteboard material, not a backlog.

**Correction to v1.** In the first version I called RETURN's photo + location direction "a pivot nothing in the record supports." With the 6/18 transcript, that's **wrong and I'm retracting it.** On 6/18 the whole team converged on location-tagged time capsules with photos — Nisa even named location-locking as the key differentiator. RETURN is **downstream of team consensus**, not a rogue doc. What's still true: RETURN *reframes* that consensus in specific ways and **fakes the very feature the team called the differentiator** (see Q1–Q2).

**The pattern in how we split (named once).** Aaryan consistently takes the automate/maximize side; Derek consistently takes the intentional/control side. On 6/18 this surfaced as **passive ingestion (Aaryan) vs. intentional capsule creation (Derek)** — and for once it **resolved cleanly into a hybrid** (passive backend, intentional frontend). That's the template for resolving the rest: name whose instinct each fork serves, then split backend/frontend or floor/ceiling.

**Quick read on all four (grounded in the 6/18 record, one meeting's worth):**

- **Aaryan** — backend/automation and vision: principle graph from multi-source data, passive ingestion, snapshot-graph "talk to past you," and the sharp self-critique ("are we just Apple Journal with principles?").
- **Derek** — meaning and user control: "talk to past versions of yourself," intentional input over passive capture, principle graph as the discovery engine, mood heatmaps.
- **Nisa** — product differentiation and shippability: **location-locking as the differentiator**, iMessages miss emotional context (need photos + mood), web-app-on-mobile now / native iOS later.
- **Selin** — user experience and wellbeing: the interactive "describe your stress → surface how you handled it before" framing, and the **only person flagging a wellbeing risk** (unhealthy nostalgia / repeating the past instead of growing).

---

## 1. The central product question now

The team agreed on **time capsules** (intentional, location-tagged, photos + notes, **locked until you physically return**). RETURN keeps a "capsule UI" but its 24h plan marks the **geofenced unlock as FAKE** ("an 'I'm back' button") and frames the whole thing as **"photo in → reconstruct a moment,"** which is retrieval-first, not intentional-creation-first.

So the agreed differentiator and the built demo don't fully line up.

**Q1. Is the hero interaction *intentional capsule creation that locks until return* (6/18 consensus) or *photo-in reconstruction* (RETURN)?**
- On record: 6/18 team converged on intentional, location-locked capsules; Nisa called location-locking the differentiator. RETURN's headline, worked trace, and BUILD list are reconstruction-first.
- Current answer: **close but not the same; unreconciled in writing.** Decide which one opens the 4-minute pitch.
- To close: pick the demo's first beat in Hour 0.

**Q2. If we're faking the geofenced unlock, does the differentiator survive?**
- On record: location-locking = Nisa's stated key differentiator; RETURN marks geofence/place-clustering **FAKE** for 24h.
- Current answer: a button-triggered "I'm back" demo is a legitimate fake — but only if the *experience* of sealing/returning is shown and the pitch doesn't claim live GPS geofencing.
- To close: confirm the demo shows the lock/unlock UX, and agree on honest pitch wording about what's real.

**Q3. "Apple Journal with principles" — what's the defensible unique value?**
- On record: Aaryan raised the risk directly; Nisa answered "location-locking"; Derek answered "the backend principle graph surfaces patterns you couldn't find yourself."
- Current answer: **two candidate differentiators on the table** (location-locked revisitation vs. the principle-graph discovery engine). Not yet a single sentence.
- To close: write the one-line "why this isn't Apple Journal" the team will say to judges.

---

## 2. Product & scope

**Q4. Passive vs. intentional data collection.**
- On record: Aaryan — automatic ingestion (photos, messages, LLM exports). Derek — intentional input feels more meaningful and gives control.
- Current answer: **RESOLVED — hybrid.** Backend passively ingests to build principles; frontend interaction is intentional capsule creation + optional journaling. Clean resolution; don't reopen.

**Q5. What surfaces to the user vs. stays backend?**
- On record: Aaryan — **principles are the only frontend-facing concept**; semantic/episodic memory stays backend. Reflection is **conversational, not recommendations** ("Do you remember when X?") to preserve agency.
- Current answer: **largely settled.** One tension to resolve → Q12 (Derek's "recommend a capsule when the user needs emotional support" is a recommendation, which cuts against "ask, don't recommend").

**Q6. Modality / data sources for v1.**
- On record: photos + location + optional text to start, expand if time (Aaryan: photo ingestion adds complexity). Nisa: need explicit **mood input**. Nostalgia "sensory layering" floated: timestamps, **weather, music (Spotify), voice notes**.
- Current answer: **core set agreed** (photo + location + text + mood). Weather/Spotify/voice are **unscoped extras**.
- To close: explicitly bucket weather/Spotify/voice as ceiling-only so they don't creep into the floor.

**Q7. Platform.**
- On record: Nisa — **web app on mobile** as the prototype; defer native iOS to post-hackathon.
- Current answer: **settled.**

**Q8. Project name.**
- "RETURN" is still a working title. Five-minute decision.

---

## 3. Architecture & engineering

**Q9. Memory engine: Hindsight vs. Redis-native vs. both.**
- On record: Aaryan — Hindsight (four networks; principles live in "Opinions"). Derek — Redis-native, more controllable. 6/18 deferred this to offline/whiteboard. RETURN lists **both** with no boundary.
- Current answer: **still open.** One system or two? If two, write the one-line split (Hindsight = networks/principle graph; Redis = abstraction vector index) and confirm it's not redundant.
- To close: decide at the whiteboard. **Half of the go/no-go gate (Q19).**

**Q10. Local vs. remote inference.**
- On record: Aaryan — local (Gemma) as a trust differentiator. Derek — remote critic, pragmatic. Not discussed 6/18.
- Current answer: RETURN resolves it **remote for the 24h build** ("sell the privacy boundary as design intent"), local as north-star only.
- To close: confirm local is **formally deferred**, then fix the honesty problem this creates → Q14.

**Q11. Principle-graph schema & "talk to past you."**
- On record: Derek owned the schema. Aaryan proposed **snapshotting the principle graph at each capsule creation** so you can talk to a past self with that historical context. RETURN supplies a concrete schema (HDBSCAN nodes; alignment/contradiction edges via NLI; edge weight = evidence × critic confidence) and a temporal-cutoff persona.
- Current answer: **a schema and a mechanism exist**; whether Derek ratified RETURN's specific version isn't on record.
- To close: Derek confirms or amends RETURN's schema; confirm the snapshot-at-capsule mechanic is how "talk to past you" is fed.

**Q12. Mood heatmaps & "recommend a capsule for emotional support."**
- On record: Derek proposed AI mood heatmaps (location ↔ happy/stress) and recommending capsules when the user needs support.
- Current answer: **net-new, partly in tension** with Aaryan's "ask, don't recommend" and with the absence of crisis handling (Q13). Recommending nostalgia to someone in distress is exactly the risky path Selin flagged.
- To close: decide if heatmaps are in scope, and gate any "support" recommendation behind Q13.

---

## 4. Safety, wellbeing, trust

**Q13. Crisis detection — still unowned.**
- On record: an open question in every design doc; **RETURN doesn't mention it** (verified: zero mentions of crisis/distress/self-harm). 6/18 didn't assign it.
- Current answer: **still the most serious gap.** The app now explicitly invites people to revisit emotionally charged places/moments and Derek wants it to act "when the user needs emotional support" — with no tripwire behind it.
- To close: name an owner and a v1 (even a keyword/classifier that halts and redirects). Non-negotiable before running on anyone's real data.

**Q14. Is the privacy framing honest if the demo runs remote?**
- On record: RETURN sells "local-first / data stays home" while running Claude remote for 24h.
- Current answer: abstraction-only egress is a real mitigation, but the wording can overclaim.
- To close: agree the exact phrasing ("local-first architecture, abstraction-only egress, remote inference in this build").

**Q15. Unhealthy nostalgia (Selin's concern).**
- On record: Selin — the app could encourage unhealthy nostalgia / repeating the past instead of growth. Aaryan — principles extract *values*, enabling new experiences aligned with them.
- Current answer: **a real design counter exists** (principles, not raw replay) but it's a claim, not a mechanic. This is adjacent to but not the same as crisis detection.
- To close: give Selin ownership of one concrete wellbeing guardrail (e.g., the reflection ends on a forward-looking question, never "go back to how it was").

---

## 5. Demo & execution

**Q16. Roles — still unassigned.**
- On record: 6/18 deferred "detailed tech stack and component breakdown" to the **start-of-hackathon whiteboard.** No one owns backend/ML/frontend/pitch yet.
- Current answer: **undefined for all four** — the only true remaining [GAP], and it blocks RETURN's hour-by-hour timeline.
- To close: assign at the whiteboard, Hour 0–1.

**Q17. Demo subject: whose data, which capsule/thread/photo?**
- On record: open. The team plans to use the hackathon itself as real-time demo data.
- Current answer: **undecided.** RETURN assumes "one person's data, one rich thread, pre-curated before Saturday."
- To close: name the person and the capsule now.

**Q18. Ratify RETURN's BUILD / FAKE / CUT line.**
- On record (RETURN's proposal): **BUILD** abstraction, storyline + citations, 5–7-node principle graph, retrieve + 1 critic, capsule UI, talk-to-past-you (light). **FAKE** place clustering, geofence. **CUT** entity resolution, local Gemma, full multi-source ingestion, **consolidation/flywheel ("vision, not v1")**.
- Current answer: one doc's proposal, not a team vote. Note it **FAKEs Nisa's differentiator** (location) and **CUTs Aaryan's flywheel**.
- To close: thumbs-up/down as a team; confirm Nisa accepts faking location and Aaryan accepts cutting the flywheel.

**Q19. THE GATE — have abstractions been validated on real data?**
- On record: Aaryan's pre-event task (run extraction on real iMessage/Instagram; test Gemma). Status **not recorded.** RETURN: "if abstractions are noisy, the day gets spent debugging the floor."
- Current answer: **unknown, and it determines viability.**
- To close: yes/no with evidence in Hour 0. If no, build it before any UI.

**Q20. Logistics — mostly handled.**
- On record (settled): Nisa arrives ~9:30am Sat; Derek ~10am; Aaryan has hotel + possible crash space. **2-hour check-in cadence** during the build. Budget fine (<$50 API; Cursor Pro; $2,000 Grok credits; sponsor APIs). Derek sends ETA ~1hr before arrival.

---

## 6. Already settled — do not relitigate

- **Hybrid passive/intentional model** (Q4) — backend ingests, frontend is intentional capsules.
- **Single-player only**; social layer out of scope (all docs).
- **Definition of done:** at least one non-obvious, grounded insight per person from their own data (all docs).
- **Principles are the flagship, frontend-facing concept**; conversational reflection over recommendations.
- **Pipeline vocabulary:** Utterance → Episode → Abstraction → Cluster → Connection (→ principle graph). Adaptive per-conversation temporal windowing.
- **Build order:** extraction → clustering → critic → connections → elicitation. Extraction is the floor and the top risk.
- **Platform** = web on mobile, iOS later (Q7). **Entity resolution** deferred. **Output-style mirroring** out of scope for v1.
- **No more pre-hackathon meetings**; resolve offline + at the start whiteboard. **2-hour check-ins.**

---

## 7. Differences matrix (the straight version)

| Decision | Aaryan | Derek | Nisa | Selin | Status |
|---|---|---|---|---|---|
| Hero interaction | backend principle graph + reconstruction | intentional capsules; talk to past self | location-locked capsules (the differentiator) | describe-stress → surface past situation | **Open (Q1)** |
| Passive vs intentional | passive/automatic ingest | intentional input, more control | photos + mood needed for emotion | — | **Resolved: hybrid** |
| What's user-facing | principles only | principle-graph discovery | location-lock UX | agency-preserving UX | Settled |
| Place/location | data source | contextual surfacing | **key differentiator** | — | Core, but **FAKEd in 24h (Q2)** |
| Memory engine | Hindsight | Redis-native | — | — | **Open (Q9, gate)** |
| Local vs remote | local (Gemma) | remote pragmatic | — | — | Remote for 24h |
| Recommend vs ask | ask, don't recommend | recommend capsules for support | — | wary of nostalgia loops | **Tension (Q12/Q15)** |
| Flywheel | the crux | (not opposed) | — | — | **CUT in 24h — confirm** |
| Wellbeing risk | values → new experiences | — | — | **raised it** | Needs an owner (Q15) |
| Crisis detection | open | open | — | adjacent concern | **Unowned (Q13)** |
| Roles | — | — | — | — | **Unassigned (Q16)** |

---

## 8. Decide at the Hour-0 whiteboard (ordered)

1. **Q19** — confirm abstractions work on real data. If not, build that first. *(gate)*
2. **Q9** — Hindsight vs Redis vs both. *(gate)*
3. **Q1–Q3** — capsule-creation vs photo-in for the hero beat; does the location differentiator survive faking; the one-line "not Apple Journal."
4. **Q16 / Q17** — assign all four roles; pick the demo person + capsule.
5. **Q13 + Q15** — owner + v1 for crisis detection and one nostalgia guardrail (Selin). *(non-negotiable)*
6. **Q18** — ratify BUILD/FAKE/CUT, incl. faking location (Nisa) and cutting the flywheel (Aaryan).
7. Remainder (Q6 extras, Q10/Q11/Q12/Q14, Q8) follows.

---

*Sources (local files): `team_trasncript_2.md` (6/18 team huddle) · `transcript.md`, `slack_summary_after_design_doc.md`, `team_transcript.md` (6/14 Aaryan+Derek) · `RETURN-architecture.pdf` · `unified-design-doc-v2.docx` · `design-doc.docx` · `Design Doc v0.docx`. 6/18 huddle thread: https://ai-hackathon-2026-hq.slack.com/files/USLACKBOT/F0BBGHHFVV1/huddle_transcript*
