import { useEffect, useState } from "react";

import { LadderScene, type LadderPhase } from "./LadderScene.tsx";
import type { DemoData, Principle, RawStreamItem, TraceExample } from "./types.ts";
import { WindowingScene, type WindowPhase } from "./WindowingScene.tsx";

/** Build the forward-pass trace for whichever principle the user selected. */
function buildTrace(p: Principle, data: DemoData): TraceExample {
  const mems = data.linked_memories.filter((m) => p.memory_ids.includes(m.id));
  // prefer an imessage-backed memory (cleanest raw rows), else the first one
  const mem = mems.find((m) => m.source === "imessage") ?? mems[0] ?? null;
  const cluster = data.clusters.find((c) => c.principle_id === p.id) ?? null;
  const merge = data.forward.merges.find((m) => m.survivor.id === p.id) ?? null;

  // raw messages flowing in: this principle's own raw snippets, padded from the
  // global stream so the windowing scene still looks full.
  const own: RawStreamItem[] = mems
    .flatMap((m) => m.raw_sample)
    .slice(0, 9)
    .map((r, i) => ({ source: r.source, content: r.content.slice(0, 60), window: i % 3 }));
  const raw_stream = own.length >= 6 ? own : [...own, ...data.trace_example.raw_stream].slice(0, 18);

  return {
    raw_rows: mem ? mem.raw_sample.slice(0, 3) : [],
    raw_stream,
    memory: mem
      ? { text: mem.text, source: mem.source, store: mem.type === "semantic" ? "semantic" : "episodic" }
      : { text: p.text, source: "—", store: "episodic" },
    cluster_id: p.id,
    cluster_point: cluster ? { x: cluster.cx, y: cluster.cy } : { x: 0.5, y: 0.5 },
    principle: { id: p.id, text: p.text },
    merge,
  };
}

/** Stage keys, in order. Each maps to one panel of the single-trace narration. */
const STAGES = [
  "raw",
  "window",
  "memory",
  "store",
  "embed",
  "cluster",
  "principle",
  "merge",
  "link",
] as const;
type StageKey = (typeof STAGES)[number];

const TITLE: Record<StageKey, string> = {
  raw: "1 · raw messages",
  window: "2 · windowing",
  memory: "3 · memories",
  store: "4 · memory store",
  embed: "5 · embedding",
  cluster: "6 · clustering",
  principle: "7 · principle",
  merge: "8 · merge",
  link: "9 · link",
};

/** The first three stages are the HTML windowing scene; the rest are the SVG. */
const SCENE_PHASE: Partial<Record<StageKey, WindowPhase>> = {
  raw: "stream",
  window: "window",
  memory: "memory",
};

/** Stages after the windowing scene map to the abstract HTML ladder phases. */
const LADDER_PHASE: Partial<Record<StageKey, LadderPhase>> = {
  store: "store",
  embed: "embed",
  cluster: "cluster",
  principle: "principle",
  merge: "merge",
  link: "link",
};

interface Props {
  data: DemoData;
  principle: Principle | null;
  onExit: () => void;
}

export function ForwardPass({ data, principle, onExit }: Props) {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(true);

  // restart the walkthrough whenever a different principle is selected
  useEffect(() => {
    setI(0);
    setPlaying(true);
  }, [principle?.id]);

  useEffect(() => {
    if (!playing) return;
    const id = setTimeout(() => {
      setI((prev) => (prev + 1 < STAGES.length ? prev + 1 : prev));
      if (i + 1 >= STAGES.length) setPlaying(false);
    }, 2600);
    return () => clearTimeout(id);
  }, [i, playing]);

  if (!principle) {
    return (
      <div className="forward flow">
        <div className="fw-empty">
          <div className="fw-empty-h">pick a principle</div>
          <div className="fw-empty-b">
            select one from the list or the graph, then watch it built from the ground up.
          </div>
          <button className="fw-exit" onClick={onExit}>
            ◂ back to graph
          </button>
        </div>
      </div>
    );
  }

  const t = buildTrace(principle, data);
  const key = STAGES[i]!;
  const scenePhase = SCENE_PHASE[key];
  const ladderPhase = LADDER_PHASE[key];

  return (
    <div className="forward flow">
      <div className="trace-scroll">
        {scenePhase && <WindowingScene items={t.raw_stream} phase={scenePhase} />}
        {ladderPhase && (
          <LadderScene
            t={t}
            clusters={data.clusters}
            edges={data.edges}
            principles={data.principles}
            phase={ladderPhase}
          />
        )}
      </div>

      <div className="fw-card flow-card">
        <div className="fw-title">{TITLE[key]}</div>
        <div className="fw-body">{caption(key, t)}</div>
        <div className="fw-controls">
          <button onClick={() => setI((p) => Math.max(0, p - 1))} disabled={i === 0}>
            ‹ back
          </button>
          <button onClick={() => setPlaying((p) => !p)}>{playing ? "❚❚ pause" : "▶ play"}</button>
          <button onClick={() => setI((p) => Math.min(STAGES.length - 1, p + 1))} disabled={i === STAGES.length - 1}>
            next ›
          </button>
          <button className="fw-exit" onClick={onExit}>
            explore ↗
          </button>
        </div>
      </div>
    </div>
  );
}

function caption(k: StageKey, t: TraceExample): string {
  switch (k) {
    case "raw":
      return `${t.raw_stream.length} raw messages stream in from across your data — tagged by source.`;
    case "window":
      return "Hindsight groups them into temporal windows — conversations that belong together.";
    case "memory":
      return "Each window is distilled into a memory: an extracted fact about you.";
    case "store":
      return `This fact went to the ${t.memory.store} store. The exact memory: “${t.memory.text.slice(0, 70)}…”`;
    case "embed":
      return "The fact is embedded into vector space — one point among all the memories.";
    case "cluster":
      return "An agent runs over each cluster; this point's cluster is selected, the rest stay grey.";
    case "principle":
      return `That cluster mints a principle: “${t.principle.text}”`;
    case "merge":
      return t.merge
        ? `Near-duplicate principles collapse — this one absorbs “${t.merge.absorbed[0]?.text ?? ""}”.`
        : "Near-duplicate principles collapse into one.";
    case "link":
      return "Finally, typed edges connect related principles into a graph.";
    default:
      return "";
  }
}

export const FORWARD_STAGE_KEYS = [...STAGES];
