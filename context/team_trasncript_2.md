:headphones: Huddle notes: 6/18/26 with @selin mutlu and 3 othersAI took notes for this huddle from 5:16:18 PM - 7:02:21 PM EDT. @Derek Chu, @selin mutlu, @Aaryan Rampal, and @Nisa Keshwani designed a location-based memory app combining time capsules, principle extraction, and nostalgia features for an AI hackathon, settling on a hybrid approach balancing user intentionality with AI-driven insights. View huddle in channel

:handshake: Attendees

@Derek Chu, @Aaryan Rampal, @Nisa Keshwani, and @selin mutlu

:star: Summary

* Core App Concept: Time Capsules and Principles
    * @Derek Chu proposed letting users talk to past versions of themselves by reviewing past messages and photos to see how they've changed [5:09], [5:27].
    * @selin mutlu envisioned an interactive app where users describe current stress or emotions, and the system surfaces past similar situations and how they handled them [6:09], [6:27].
    * Team converged on time capsules as the primary user interaction: users intentionally create location-tagged capsules with photos, notes, and reflections that lock until revisited [9:54], [10:06].
    * @Aaryan Rampal proposed a backend graph structure extracting principles (core values/patterns) from multi-source data (iMessages, Claude exports, photos, brain dumps) without requiring manual user tagging [32:23], [33:07].
* Passive vs. Intentional Data Collection
    * @Aaryan Rampal advocated for automatic data ingestion from photos, messages, and LLM conversations to build rich user profiles; @Derek Chu countered that intentional user input (time capsule creation) feels more meaningful and gives users control [21:57], [51:44].
    * Team agreed on hybrid model: backend passively ingests data to build principles, but frontend interaction is intentional time capsule creation with optional journaling [59:03], [1:04:53].
    * @Nisa Keshwani raised concern that iMessages alone don't capture emotional context (e.g., curt texts during happy moments), so photos and explicit mood input are necessary [33:31], [33:49].
    * @Aaryan Rampal clarified that principles should be the only frontend-facing concept; backend can track semantic and episodic memory without overwhelming users [1:21:58], [1:22:16].
* Differentiation from Apple Journal
    * @Aaryan Rampal noted the app risks being "Apple Journal with principles" and questioned what unique value it adds [1:30:23], [1:31:49].
    * @Nisa Keshwani identified location-locking as key differentiator: capsules remain sealed until user returns to that place, creating intentional revisitation moments [1:32:37], [56:37].
    * @Derek Chu emphasized the backend principle graph enables discovery of personal patterns and connections users wouldn't find manually, and the app surfaces relevant past experiences contextually [1:33:27], [1:35:30].
    * @Aaryan Rampal proposed conversational reflection rather than recommendations: asking "Do you remember when X happened?" to prompt user recollection and agency instead of telling them what to do [1:36:52], [1:37:15].
* AI Integration and Nostalgia Design
    * @Derek Chu suggested AI could generate mood heatmaps showing which locations correlate with happiness or stress, and recommend capsules when users need emotional support [13:20], [14:20].
    * @Aaryan Rampal proposed snapshotting the principle graph at each time capsule creation so users can "talk to" a past version of themselves with historical context [1:07:07].
    * Team discussed maximizing nostalgia by layering sensory data: location, photos, timestamps, weather, music (via Spotify), and voice notes to recreate the moment [1:06:13], [1:09:14].
    * @selin mutlu raised concern about the app encouraging unhealthy nostalgia or repeated past behaviors rather than growth; @Aaryan Rampal countered that principles extract underlying values, enabling new experiences aligned with those values [1:10:33], [1:11:58].
* Technical Scope and Platform Decisions
    * @Nisa Keshwani proposed building a web app accessible on mobile as a prototype, deferring native iOS development to post-hackathon [27:29], [27:34].
    * @Aaryan Rampal noted photo ingestion adds complexity; team agreed to start minimal (photos + location + optional text) and expand if time permits [16:04], [29:48].
    * @Aaryan Rampal estimated API costs under $50 total and noted team has access to Cursor Pro, Grok AI credits ($2000), and hackathon sponsor APIs [18:08], [19:14].
    * Team agreed to defer detailed tech stack and component breakdown to offline work, planning a 30–40 minute whiteboarding session at hackathon start [1:38:56], [1:40:00].
* Logistics and Next Steps
    * @Nisa Keshwani will arrive ~9:30am Saturday; @Derek Chu arriving around opening ceremony (10am); @Aaryan Rampal has hotel access and knows people at Berkeley with potential crash space [1:43:51], [1:44:10], [1:46:45].
    * Team will brainstorm input/output specifications and research sponsor APIs offline via Slack; no additional pre-hackathon meetings planned [1:41:19], [1:40:59].
    * @Aaryan Rampal proposed check-in cadence every 2 hours during hackathon to avoid silos and coordinate when blocked [1:48:55].
    * Team will explore Berkeley food and attractions (matcha, food scene) during breaks and use hackathon experience as real-time data for demo [1:42:34], [1:50:27].

:white_check_mark: Action items

* Team to brainstorm and document input/output specifications and data flow offline before Saturday [1:41:19].
* Research hackathon sponsor APIs and available credits to finalize tech stack [20:14].
* Prepare 30–40 minute whiteboarding session at hackathon start to finalize component breakdown and task allocation [1:40:00].
* @Derek Chu to send ETA message ~1 hour before arrival Saturday [1:45:27].
* Establish 2-hour check-in cadence during hackathon via chat to coordinate and unblock [1:48:55].

This tool uses AI to generate notes, so some information may be inaccurate. They're based on the huddle transcript and thread and can be edited anytime.
https://ai-hackathon-2026-hq.slack.com/files/USLACKBOT/F0BBGHHFVV1/huddle_transcript

