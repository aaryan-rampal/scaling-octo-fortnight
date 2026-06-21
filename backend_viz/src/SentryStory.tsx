import { motion } from "motion/react";

import type { Observability } from "./types.ts";

interface Props {
  obs: Observability;
  onClose: () => void;
}

/** Overlay telling the real Sentry debugging story: the loop + the actual fix. */
export function SentryStory({ obs, onClose }: Props) {
  const { story } = obs;
  return (
    <div className="sentry-overlay" onClick={onClose}>
      <motion.div
        className="sentry-panel"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 220, damping: 26 }}
      >
        <button className="close" onClick={onClose}>
          ×
        </button>
        <h2>{story.title}</h2>

        {/* the whole loop, Mermaid-style */}
        <div className="story-flow">
          {story.steps.map((s, i) => (
            <motion.div
              key={s.label}
              className="story-step"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.06 * i }}
            >
              <div className="story-step-h">{s.label}</div>
              <div className="story-step-d">{s.detail}</div>
              {i < story.steps.length - 1 && <span className="story-arrow">▾</span>}
            </motion.div>
          ))}
        </div>

        {/* the specific fix: before / after */}
        <div className="story-code">
          <div className="code-col before">
            <div className="code-tag">before · serial, ~3.5s each</div>
            <pre>{story.code_before}</pre>
          </div>
          <div className="code-col after">
            <div className="code-tag">after · 8 workers + traced</div>
            <pre>{story.code_after}</pre>
          </div>
        </div>

        <div className="story-foot">
          <code>{story.commit}</code>
          <a href={obs.trace_url} target="_blank" rel="noreferrer">
            view the 15.1s trace in Sentry ↗
          </a>
        </div>
      </motion.div>
    </div>
  );
}
