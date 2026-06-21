import { AnimatePresence, motion } from "motion/react";

import { relationColor } from "./graph.ts";
import type { Cluster, Edge, Principle, TraceExample } from "./types.ts";

const SOURCE_COLOR: Record<string, string> = {
  claude: "#a78bfa",
  imessage: "#34d399",
  spotify: "#f472b6",
  photos: "#fbbf24",
};
const srcColor = (s: string) => SOURCE_COLOR[s] ?? "#64748b";

/** The abstract half of the trace: store -> embed -> cluster -> principle -> merge -> link. */
export type LadderPhase = "store" | "embed" | "cluster" | "principle" | "merge" | "link";

/** Center + diameter (all in [0,1] field coords) that snugly encloses a cluster's dots. */
function ringBox(c: Cluster): { cx: number; cy: number; size: number } {
  const xs = c.members.map((m) => m.x);
  const ys = c.members.map((m) => m.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const pad = 0.06; // breathing room around the outermost dot
  const size = Math.max(maxX - minX, maxY - minY) + pad * 2;
  return { cx, cy, size };
}

const SPRING = { type: "spring" as const, stiffness: 200, damping: 26 };

interface Props {
  t: TraceExample;
  clusters: Cluster[];
  edges: Edge[];
  principles: Principle[];
  phase: LadderPhase;
}

export function LadderScene({ t, clusters, edges, principles, phase }: Props) {
  if (phase === "store") return <StorePhase t={t} />;
  if (phase === "embed" || phase === "cluster")
    return <EmbedPhase t={t} clusters={clusters} clustered={phase === "cluster"} />;
  return <PrinciplePhase t={t} phase={phase} edges={edges} principles={principles} />;
}

/** Two memory-store cards; the one this fact landed in lights up + shows the fact. */
function StorePhase({ t }: { t: TraceExample }) {
  const stores: Array<"episodic" | "semantic"> = ["episodic", "semantic"];
  return (
    <div className="ladder">
      <div className="store-row">
        {stores.map((s) => {
          const on = t.memory.store === s;
          return (
            <motion.div
              key={s}
              className={`store-card ${on ? "on" : "off"}`}
              animate={{ scale: on ? 1.04 : 0.96, opacity: on ? 1 : 0.4 }}
              transition={SPRING}
            >
              <div className="store-title">{s}</div>
              {on && (
                <motion.div
                  className="store-fact"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ ...SPRING, delay: 0.2 }}
                >
                  “{t.memory.text}”
                </motion.div>
              )}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The embedding field: every cluster's dots laid out in 2D. When `clustered`,
 * the trace's own cluster stays vivid and everything else fades to grey, with a
 * ring drawn around the selected cluster — the "agent picks this cluster" beat.
 */
function EmbedPhase({
  t,
  clusters,
  clustered,
}: {
  t: TraceExample;
  clusters: Cluster[];
  clustered: boolean;
}) {
  const target = clusters.find((c) => c.principle_id === t.cluster_id) ?? null;
  const ring = target ? ringBox(target) : null;
  return (
    <div className="ladder">
      <div className="embed-field">
        {clustered && ring && (
          <motion.div
            className="cluster-ring"
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={SPRING}
            style={{
              left: `${ring.cx * 100}%`,
              top: `${ring.cy * 100}%`,
              width: `${ring.size * 100}%`,
              height: `${ring.size * 100}%`,
              // centre via Framer's own transform so `scale` composes with it
              // (CSS translate(-50%,-50%) would be overwritten by the animation)
              x: "-50%",
              y: "-50%",
            }}
          />
        )}
        {clusters.flatMap((c) =>
          c.members.map((m, mi) => {
            const inTarget = c.principle_id === t.cluster_id;
            const lit = !clustered || inTarget;
            return (
              <motion.span
                key={`${c.principle_id}-${mi}`}
                className="embed-dot"
                initial={{ opacity: 0, scale: 0 }}
                animate={{
                  opacity: lit ? 1 : 0.18,
                  scale: 1,
                  backgroundColor: lit ? srcColor(m.source) : "#3a3550",
                }}
                transition={{ ...SPRING, delay: (mi % 6) * 0.02 }}
                style={{ left: `${m.x * 100}%`, top: `${m.y * 100}%`, x: "-50%", y: "-50%" }}
              />
            );
          }),
        )}
        <div className="embed-cap">
          {clustered ? "an agent picks this cluster · rest dim" : "every memory, embedded in space"}
        </div>
      </div>
    </div>
  );
}

/** Principle minted, then merge, then link — each beat a clean reveal. */
function PrinciplePhase({
  t,
  phase,
  edges,
  principles,
}: {
  t: TraceExample;
  phase: "principle" | "merge" | "link";
  edges: Edge[];
  principles: Principle[];
}) {
  if (phase === "link") return <LinkDiagram t={t} edges={edges} principles={principles} />;
  return (
    <div className="ladder princ-stack">
      <AnimatePresence mode="popLayout">
        <motion.div
          key="principle"
          layout
          className="princ-card"
          initial={{ opacity: 0, y: 16, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={SPRING}
        >
          <div className="princ-tag">principle</div>
          {t.principle.text}
        </motion.div>

        {phase === "merge" && t.merge && (
          <motion.div
            key="merge"
            layout
            className="merge-card"
            initial={{ opacity: 0, x: 30 }}
            animate={{ opacity: 1, x: 0 }}
            transition={SPRING}
          >
            <div className="merge-tag">✦ absorbs near-duplicate</div>
            “{t.merge.absorbed[0]?.text ?? ""}”
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const RELATION_LABEL: Record<string, string> = {
  supports: "supports",
  refines: "refines",
  contradicts: "contradicts",
  generalizes: "generalizes",
};

/** This principle at center; its connected principles fan out, edges by type. */
function LinkDiagram({
  t,
  edges,
  principles,
}: {
  t: TraceExample;
  edges: Edge[];
  principles: Principle[];
}) {
  const textById = new Map(principles.map((p) => [p.id, p.text]));
  const neighbors = edges
    .filter((e) => e.src === t.principle.id || e.dst === t.principle.id)
    .map((e) => {
      const otherId = e.src === t.principle.id ? e.dst : e.src;
      return { id: otherId, relation: e.relation, text: textById.get(otherId) ?? "" };
    })
    .filter((n) => n.text)
    .slice(0, 7);

  const relsPresent = [...new Set(neighbors.map((n) => n.relation))];
  const cx = 50;
  const cy = 50;
  const R = 38; // radius (in %) of the neighbor ring

  return (
    <div className="ladder link-stage">
      <div className="link-field">
        <svg viewBox="0 0 100 100" className="link-svg" preserveAspectRatio="none">
          {neighbors.map((n, i) => {
            const ang = (2 * Math.PI * i) / Math.max(neighbors.length, 1) - Math.PI / 2;
            const x = cx + R * Math.cos(ang);
            const y = cy + R * Math.sin(ang);
            return (
              <motion.line
                key={n.id}
                x1={cx}
                y1={cy}
                x2={x}
                y2={y}
                stroke={relationColor(n.relation)}
                strokeWidth={0.7}
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 0.9 }}
                transition={{ ...SPRING, delay: 0.15 + i * 0.08 }}
              />
            );
          })}
        </svg>

        <div className="link-center">{t.principle.text}</div>

        {neighbors.map((n, i) => {
          const ang = (360 * i) / Math.max(neighbors.length, 1) - 90;
          const x = cx + R * Math.cos((ang * Math.PI) / 180);
          const y = cy + R * Math.sin((ang * Math.PI) / 180);
          return (
            <motion.div
              key={n.id}
              className="link-node"
              style={{ left: `${x}%`, top: `${y}%`, borderColor: relationColor(n.relation) }}
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ ...SPRING, delay: 0.2 + i * 0.08 }}
            >
              <span className="link-rel" style={{ color: relationColor(n.relation) }}>
                {RELATION_LABEL[n.relation] ?? n.relation}
              </span>
              {n.text.slice(0, 52)}
            </motion.div>
          );
        })}
      </div>

      <div className="link-legend">
        {relsPresent.map((r) => (
          <span key={r} className="link-leg-item">
            <span className="link-leg-dot" style={{ background: relationColor(r) }} />
            {RELATION_LABEL[r] ?? r}
          </span>
        ))}
        {neighbors.length === 0 && <span className="link-leg-item">no links for this principle</span>}
      </div>
    </div>
  );
}
