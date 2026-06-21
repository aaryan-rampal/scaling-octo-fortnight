/** Transform the flat demo data into a 3-layer ladder graph (nodes + links). */

import type { DemoData, GraphLink, GraphNode } from "./types.ts";

/** Vertical band targets (graph-space y) for the ladder. Negative = up. */
export const BAND = { principle: -260, memory: 0, raw: 260 } as const;

export const COLORS = {
  principle: "#a78bfa",
  principleHot: "#f472b6",
  episodic: "#a78bfa",
  semantic: "#34d399",
  entity: "#fbbf24",
  raw: "#64748b",
  dim: "#2a2640",
} as const;

export interface BuiltGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  /** principleId -> set of node ids (memories + raws) in its trace. */
  trace: Map<string, Set<string>>;
}

/** Build the ladder graph. Each linked memory + its raw snippets become nodes. */
export function buildGraph(data: DemoData): BuiltGraph {
  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];
  const trace = new Map<string, Set<string>>();

  // owner: memory_id -> first principle that cites it (for colour grouping)
  const owner = new Map<string, string>();
  for (const p of data.principles) {
    trace.set(p.id, new Set());
    for (const mid of p.memory_ids) if (!owner.has(mid)) owner.set(mid, p.id);
  }

  // degree per principle, so hubs render larger
  const degree = new Map<string, number>();
  for (const e of data.edges) {
    degree.set(e.src, (degree.get(e.src) ?? 0) + 1);
    degree.set(e.dst, (degree.get(e.dst) ?? 0) + 1);
  }

  for (const p of data.principles) {
    nodes.push({
      id: p.id,
      kind: "principle",
      label: p.text,
      sub: `${p.memory_ids.length} memories · ${p.raw_count} raw events`,
      layerY: BAND.principle,
      degree: degree.get(p.id) ?? 0,
    });
  }

  for (const e of data.edges) {
    links.push({ source: e.src, target: e.dst, kind: "edge", relation: e.relation });
  }

  for (const m of data.linked_memories) {
    const pid = owner.get(m.id);
    nodes.push({
      id: m.id,
      kind: "memory",
      label: m.text,
      sub: `${m.type} · ${m.source} · ${m.raw_total} raw`,
      memType: m.type,
      source: m.source,
      layerY: BAND.memory,
      ...(pid ? { principleId: pid } : {}),
    });
    // every principle citing this memory gets it in its trace + a p->m link
    for (const p of data.principles) {
      if (!p.memory_ids.includes(m.id)) continue;
      trace.get(p.id)!.add(m.id);
      links.push({ source: p.id, target: m.id, kind: "p2m" });
    }
    // raw snippets under the memory
    m.raw_sample.forEach((r, i) => {
      const rid = `${m.id}__raw${i}`;
      nodes.push({
        id: rid,
        kind: "raw",
        label: r.content,
        sub: `raw · ${r.source}`,
        source: r.source,
        layerY: BAND.raw,
        ...(pid ? { principleId: pid } : {}),
      });
      links.push({ source: m.id, target: rid, kind: "m2r" });
      for (const p of data.principles) {
        if (p.memory_ids.includes(m.id)) trace.get(p.id)!.add(rid);
      }
    });
  }

  return { nodes, links, trace };
}

/** Colour for a node given selection state. */
export function nodeColor(n: GraphNode, lit: Set<string> | null): string {
  const dimmed = lit !== null && !lit.has(n.id) && n.kind !== "principle";
  if (n.kind === "principle") {
    if (lit === null) return COLORS.principle;
    return lit.has(n.id) ? COLORS.principleHot : COLORS.dim;
  }
  if (dimmed) return COLORS.dim;
  if (n.kind === "raw") return memColor(n.source);
  return n.memType === "semantic" ? COLORS.semantic : COLORS.episodic;
}

/** Colour an edge by its relation type so the graph carries meaning. */
export function relationColor(relation: string | undefined): string {
  switch (relation) {
    case "contradicts":
      return "#f87171";
    case "refines":
      return "#fbbf24";
    case "generalizes":
      return "#34d399";
    default:
      return "#6d28d9"; // supports
  }
}

function memColor(source: string | undefined): string {
  switch (source) {
    case "claude":
      return "#a78bfa";
    case "imessage":
      return "#34d399";
    case "spotify":
      return "#f472b6";
    case "photos":
      return "#fbbf24";
    default:
      return COLORS.raw;
  }
}
