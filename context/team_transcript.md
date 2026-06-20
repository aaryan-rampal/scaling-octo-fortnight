:headphones: Huddle notes: 6/14/26 with @Aaryan Rampal and @Derek ChuAI took notes for this huddle from 9:20:55 PM - 10:36:40 PM EDT. @Derek Chu and @Aaryan Rampal refined design for a personal principles-tracking app using message data, focusing on scope (single-user), data pipeline architecture, and principle graph structure. View huddle in channel

:handshake: Attendees

@Aaryan Rampal and @Derek Chu

:star: Summary

* Project Scope and Design Principles
  * @Derek Chu proposed limiting scope to single-user experience, excluding multi-user social features for the hackathon. [10:48]
  * @Aaryan Rampal agreed that social/network features represent a separate domain requiring full redesign, supporting single-player scope. [12:41]
  * Both emphasized grounding all system outputs in design principles and making connections traceable back to evidence. [13:12]
* Data Ingestion and Schema Design
  * @Aaryan Rampal demonstrated iMessage export tool that queries SQLite database locally, avoiding manual data entry. [15:21]
  * @Derek Chu proposed unified schema across platforms with fields: timestamp, content, platform identity, thread ID, and response linking. [18:14]
  * @Aaryan Rampal emphasized canonicalization challenge—ensuring shared schema works across iMessage, Instagram, journals, and other sources. [19:45]
  * Both agreed to use abstraction layer to normalize data before output rather than modifying export tool directly. [18:00]
* Pipeline: Utterances, Episodes, Abstraction, Clustering
  * defined utterance as single message, episode as temporal grouping of messages within one platform about same topic. [27:58]
  * noted temporal windowing (e.g., one-hour threshold) needed to group conversations, since reply chains don't always exist. [23:57]
  * explained abstraction step extracts underlying principles from episode content, then clustering finds similar principle patterns across episodes. [28:50]
  * Both agreed connections between clusters are surfaced to user with option to trace back through pipeline for verification. [34:00]
* User Feedback and System Transparency
  * proposed two approaches: blackbox (user only sees final connection, gives yes/no) or transparent (user sees intermediate steps). [31:16]
  * favored showing minimal intermediate steps, keeping most processing hidden while allowing users to drill into reasoning if needed. [33:30]
  * agreed users should question connections and investigate principles involved, with ability to correct vault or gain confidence. [34:40]
  * Both settled on showing only clusters directly involved in a connection, not all clusters, to maintain "magic" feeling. [41:18]
* Principles as Graph Structure
  * proposed principles exist as graph/tree with edges denoting relationships, contradictions, or alignments between principles. [58:09]
  * illustrated example: principle "keep weekends free" with subprinciple "unless close friends," suggesting principles need hierarchical or connected structure. [56:32]
  * suggested using logging levels to show only strongest edges to user while keeping dense graph in backend. [1:02:18]
  * emphasized principles are flagship metric exposed to user, capturing complex feelings in short one-liners. [54:10]
* Pruning, Feedback Ingestion, and Cluster Recomputation
  * proposed pruning layer runs periodically (every 24 hours or N events) to clean up and reorganize based on user feedback. [1:06:49]
  * suggested triggering pruning when contradictions found in principles or cluster freshness metrics indicate stale data. [1:07:50]
  * noted clusters are algorithmic outputs hard to directly control; feedback should re-embed abstractions rather than modify clusters directly. [1:10:34]
  * Both agreed user feedback on connections should flow back through abstraction re-embedding to improve future clustering. [1:10:34]

:white_check_mark: Action items

* schedule one-on-one refinement chat with  on Monday or Tuesday before team-wide meeting. [1:11:48]
* schedule team-wide chat for Tuesday at 7 p.m. EST with full team. [1:13:55]
* run experiments on own data (iMessage, Instagram) to test pipeline effectiveness and principle extraction. [52:57]
* research local LLM models (e.g., Google Gemma) to evaluate running inference locally for privacy. [51:37]
* define schema for principle graph nodes, edges, and relationships before next team meeting. [1:04:13]

This tool uses AI to generate notes, so some information may be inaccurate. They're based on the huddle transcript and thread and can be edited anytime.
