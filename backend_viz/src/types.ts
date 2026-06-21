/** Shapes of `public/demo_data.json` (produced by `scripts/build_demo_data.py`). */

export type MemoryType = "episodic" | "semantic" | "entity";

export interface RawSnippet {
  source: string;
  content: string;
}

export interface Principle {
  id: string;
  text: string;
  confidence: number;
  memory_ids: string[];
  raw_count: number;
}

export interface Edge {
  src: string;
  dst: string;
  relation: string;
}

export interface LinkedMemory {
  id: string;
  text: string;
  source: string;
  fact_type: string | null;
  type: MemoryType;
  raw_sample: RawSnippet[];
  raw_total: number;
}

export interface SampledMemory {
  id: string;
  source: string;
  type: MemoryType;
  text: string;
}

export interface MergeStep {
  merged_id: string;
  survivor: { id: string; text: string };
  absorbed: { id: string; text: string }[];
}

export interface LinkStep {
  src: string;
  dst: string;
  relation: string;
}

export interface ForwardSteps {
  merges: MergeStep[];
  links: LinkStep[];
  merge_is_illustrative: boolean;
}

export interface ClusterMember {
  x: number;
  y: number;
  source: string;
}

export interface Cluster {
  principle_id: string;
  label: string;
  cx: number;
  cy: number;
  members: ClusterMember[];
}

export interface RawStreamItem {
  source: string;
  content: string;
  window: number;
}

export interface TraceExample {
  raw_rows: RawSnippet[];
  raw_stream: RawStreamItem[];
  memory: { text: string; source: string; store: "episodic" | "semantic" };
  cluster_id: string;
  cluster_point: { x: number; y: number };
  principle: { id: string; text: string };
  merge: MergeStep | null;
}

export interface DemoData {
  counts: {
    events: number;
    memories: number;
    principles: number;
    edges: number;
    linked_memories: number;
  };
  events_by_source: Record<string, number>;
  memories_by_type: Record<string, number>;
  principles: Principle[];
  edges: Edge[];
  linked_memories: LinkedMemory[];
  all_memories_sample: SampledMemory[];
  forward: ForwardSteps;
  clusters: Cluster[];
  trace_example: TraceExample;
  observability: Observability;
}

export interface ObservabilityStory {
  title: string;
  steps: { label: string; detail: string }[];
  code_before: string;
  code_after: string;
  commit: string;
}

export interface Observability {
  slowest_call_ms: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
  trace_url: string;
  story: ObservabilityStory;
}

/** A node in the force graph — one of the three ladder layers. */
export type GraphNodeKind = "principle" | "memory" | "raw";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  /** Sub-line for the tooltip (source, counts, …). */
  sub: string;
  /** Memory type, for colouring memory nodes. */
  memType?: MemoryType;
  /** Raw/memory source, for colouring. */
  source?: string;
  /** Fixed vertical band target (set per kind for the ladder layout). */
  layerY: number;
  /** The principle this node belongs to, for trace highlighting. */
  principleId?: string;
  /** Edge count for a principle node, used to scale its radius. */
  degree?: number;
  x?: number;
  y?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  kind: "edge" | "p2m" | "m2r";
  relation?: string;
}
