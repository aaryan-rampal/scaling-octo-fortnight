import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";

import { ForwardPass } from "./ForwardPass.tsx";
import { buildGraph, COLORS, nodeColor, relationColor } from "./graph.ts";
import { SentryStory } from "./SentryStory.tsx";
import { TracePanel } from "./TracePanel.tsx";
import type { DemoData, GraphLink, GraphNode, Principle } from "./types.ts";

type FG = ForceGraphMethods<GraphNode, GraphLink>;
type Mode = "forward" | "backward";

export function App() {
  const [data, setData] = useState<DemoData | null>(null);
  const [mode, setMode] = useState<Mode>("backward");
  const [selected, setSelected] = useState<Principle | null>(null);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [showStory, setShowStory] = useState(false);
  const fgRef = useRef<FG | undefined>(undefined);

  useEffect(() => {
    fetch("/demo_data.json")
      .then((r) => r.json())
      .then((d: DemoData) => setData(d));
  }, []);

  const built = useMemo(() => (data ? buildGraph(data) : null), [data]);
  const lit = useMemo(
    () => (selected && built ? (built.trace.get(selected.id) ?? new Set<string>()) : null),
    [selected, built],
  );

  // Show only principles + edges by default; reveal a principle's memory/raw
  // trace (and the links into it) only once it's selected.
  const visible = useMemo(() => {
    if (!built) return null;
    const keep = (id: string) => id === selected?.id || (lit?.has(id) ?? false);
    if (!selected) {
      return {
        nodes: built.nodes.filter((n) => n.kind === "principle"),
        links: built.links.filter((l) => l.kind === "edge"),
      };
    }
    return {
      nodes: built.nodes.filter((n) => n.kind === "principle" || keep(n.id)),
      links: built.links.filter((l) => {
        if (l.kind === "edge") return true;
        return keep(String(l.source)) && keep(String(l.target));
      }),
    };
  }, [built, selected, lit]);

  // Pin each node to its ladder band so the force layout stays in 3 rows.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-40);
    const y = fg.d3Force("y");
    if (y) return; // configured already
  }, [built]);

  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const isPrinciple = node.kind === "principle";
      const isLit = lit?.has(node.id) ?? false;
      // principles scale with edge degree so hubs stand out; others fixed
      const r = isPrinciple
        ? 5 + Math.min(7, Math.sqrt(node.degree ?? 0) * 1.8)
        : node.kind === "memory"
          ? 4
          : 2.4;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI);
      ctx.fillStyle = nodeColor(node, lit);
      ctx.fill();
      if (isPrinciple && isLit) {
        ctx.beginPath();
        ctx.arc(node.x ?? 0, node.y ?? 0, r + 5, 0, 2 * Math.PI);
        ctx.strokeStyle = COLORS.principleHot + "88";
        ctx.lineWidth = 2 / scale;
        ctx.stroke();
      }
      if (isPrinciple && scale > 1.4) {
        ctx.fillStyle = "#e8e6f0";
        ctx.font = `${11 / scale}px ui-sans-serif`;
        ctx.fillText(node.label.slice(0, 38), (node.x ?? 0) + 9, (node.y ?? 0) + 3);
      }
    },
    [lit],
  );

  const onNodeClick = useCallback(
    (node: GraphNode) => {
      if (node.kind !== "principle" || !data) return;
      const p = data.principles.find((x) => x.id === node.id) ?? null;
      setSelected(p);
    },
    [data],
  );


  if (!data || !built || !visible) return <div className="loading">loading your mind…</div>;

  return (
    <div className="app">
      <aside className="panel left">
        <h1>RETURN</h1>
        <div className="sub">your mind, traced to ground truth</div>
        <div className="modes">
          <button className={mode === "forward" ? "on" : ""} onClick={() => setMode("forward")}>
            ▶ forward
          </button>
          <button className={mode === "backward" ? "on" : ""} onClick={() => setMode("backward")}>
            ◂ trace back
          </button>
        </div>
        <div className="pills">
          <span className="pill">{data.counts.events.toLocaleString()} raw</span>
          <span className="pill">{data.counts.memories.toLocaleString()} memories</span>
          <span className="pill">{data.counts.principles} principles</span>
          <span className="pill">{data.counts.edges} edges</span>
        </div>
        <div className="plist">
          {data.principles.map((p) => (
            <button
              key={p.id}
              className={`p ${selected?.id === p.id ? "sel" : ""}`}
              onClick={() => setSelected(p)}
            >
              <span className="conf">{p.confidence.toFixed(2)}</span>
              <div className="pt">{p.text}</div>
              <div className="pm">
                {p.memory_ids.length} mem · {p.raw_count} raw
              </div>
            </button>
          ))}
        </div>
        <div className="legend">
          <span className="dot epi" /> episodic
          <span className="dot sem" /> semantic
          <span className="dot raw" /> raw
        </div>
      </aside>

      <ForceGraph2D<GraphNode, GraphLink>
        ref={fgRef}
        graphData={visible}
        backgroundColor="#0a0a12"
        nodeId="id"
        nodeCanvasObject={paintNode}
        nodePointerAreaPaint={(node, color, ctx) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x ?? 0, node.y ?? 0, node.kind === "principle" ? 8 : 5, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkColor={(l) => {
          const link = l as GraphLink;
          if (link.kind === "edge") {
            const touches = selected && (link.source === selected.id || link.target === selected.id);
            // faint relation hue by default; brighten the selected node's edges
            return relationColor(link.relation) + (selected ? (touches ? "ee" : "1f") : "55");
          }
          // p2m / m2r trace links only show under selection
          if (!selected) return "#00000000";
          const inTrace =
            (lit?.has(String(link.source)) || link.source === selected.id) &&
            (lit?.has(String(link.target)) || link.target === selected.id);
          return inTrace ? "#a78bfa77" : "#00000000";
        }}
        linkWidth={(l) => {
          const link = l as GraphLink;
          if (link.kind !== "edge") return 1;
          const touches = selected && (link.source === selected.id || link.target === selected.id);
          return touches ? 2.2 : 1;
        }}
        onNodeClick={onNodeClick}
        onNodeHover={(n) => setHovered(n)}
        cooldownTicks={120}
        onEngineStop={() => fgRef.current?.zoomToFit(400, 80)}
      />

      {hovered && (
        <div className="tip">
          <div className="th">{hovered.kind}</div>
          {hovered.label}
          {hovered.sub && <div className="tsub">{hovered.sub}</div>}
        </div>
      )}

      {mode === "backward" && (
        <TracePanel principle={selected} data={data} onClose={() => setSelected(null)} />
      )}
      {mode === "forward" && (
        <ForwardPass data={data} principle={selected} onExit={() => setMode("backward")} />
      )}

      <button className="obs-badge" onClick={() => setShowStory(true)} title="How Sentry found the bottleneck">
        <div className="obs-h">⏱ slowest LLM call</div>
        <div className="obs-dur">{(data.observability.slowest_call_ms / 1000).toFixed(1)}s</div>
        <div className="obs-sub">
          {data.observability.model.split("/").pop()} ·{" "}
          {data.observability.input_tokens.toLocaleString()}→
          {data.observability.output_tokens.toLocaleString()} tok
        </div>
        <div className="obs-link">how Sentry helped ↗</div>
      </button>

      {showStory && (
        <SentryStory obs={data.observability} onClose={() => setShowStory(false)} />
      )}
    </div>
  );
}
