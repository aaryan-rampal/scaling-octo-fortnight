import { AnimatePresence, motion } from "motion/react";

import type { RawStreamItem } from "./types.ts";

const SOURCE_COLOR: Record<string, string> = {
  claude: "#a78bfa",
  imessage: "#34d399",
  spotify: "#f472b6",
  photos: "#fbbf24",
};
const srcColor = (s: string) => SOURCE_COLOR[s] ?? "#64748b";

/** Phases of the stats-video windowing animation. */
export type WindowPhase = "stream" | "window" | "memory";

interface Props {
  items: RawStreamItem[];
  phase: WindowPhase;
}

const SPRING = { type: "spring" as const, stiffness: 220, damping: 26 };

/**
 * The centerpiece scene: many raw messages fly in, then smoothly regroup into
 * temporal windows, then each window collapses into a single memory dot.
 *
 * Framer's layout animation does the heavy lifting — we only change the flexbox
 * grouping between phases and let `layout` tween every card to its new home.
 */
export function WindowingScene({ items, phase }: Props) {
  const windows = [...new Set(items.map((i) => i.window))].sort();

  if (phase === "memory") {
    return (
      <div className="win-memrow">
        {windows.map((w) => (
          <motion.div
            key={w}
            layout
            layoutId={`win-${w}`}
            transition={SPRING}
            className="win-memdot"
          >
            <div className="win-memlabel">memory {w + 1}</div>
          </motion.div>
        ))}
      </div>
    );
  }

  return (
    <div className={`win-stage ${phase}`}>
      {phase === "stream" ? (
        <motion.div layout className="win-cloud" transition={SPRING}>
          <AnimatePresence>
            {items.map((it, i) => (
              <Card key={i} it={it} index={i} />
            ))}
          </AnimatePresence>
        </motion.div>
      ) : (
        <div className="win-cols">
          {windows.map((w) => (
            <motion.div key={w} layout layoutId={`win-${w}`} transition={SPRING} className="win-col">
              <div className="win-coltitle">window {w + 1}</div>
              {items
                .filter((it) => it.window === w)
                .map((it, i) => (
                  <Card key={`${w}-${i}`} it={it} index={i} compact />
                ))}
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}

function Card({ it, index, compact }: { it: RawStreamItem; index: number; compact?: boolean }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 24, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ ...SPRING, delay: compact ? 0 : index * 0.05 }}
      className={`win-card ${compact ? "compact" : ""}`}
      style={{ borderLeftColor: srcColor(it.source) }}
    >
      <span className="win-src" style={{ color: srcColor(it.source) }}>
        {it.source}
      </span>
      <span className="win-txt">{it.content}</span>
    </motion.div>
  );
}
