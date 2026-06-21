import type { DemoData, LinkedMemory, Principle } from "./types.ts";

interface Props {
  principle: Principle | null;
  data: DemoData;
  onClose: () => void;
}

/** Right-hand detail panel: the selected principle's full provenance trace. */
export function TracePanel({ principle, data, onClose }: Props) {
  if (!principle) return null;
  const memById = new Map<string, LinkedMemory>(data.linked_memories.map((m) => [m.id, m]));
  const memories = principle.memory_ids
    .map((id) => memById.get(id))
    .filter((m): m is LinkedMemory => m !== undefined);

  const merge = data.forward.merges.find((m) => m.survivor.id === principle.id);

  return (
    <aside className="panel right open">
      <button className="close" onClick={onClose}>
        ×
      </button>
      <h2>
        traces to {memories.length} memories · {principle.raw_count} raw events
      </h2>
      <div className="ptext">{principle.text}</div>
      {merge && (
        <div className="merge-note">
          <div className="merge-h">
            ✦ merged principle
            {data.forward.merge_is_illustrative && <span className="illus"> · illustrative</span>}
          </div>
          {merge.absorbed.map((a) => (
            <div key={a.id} className="absorbed">
              absorbed “{a.text}”
            </div>
          ))}
        </div>
      )}
      {memories.map((m) => (
        <div key={m.id} className={`mem ${m.type}`}>
          <div className="src">
            {m.type} · {m.source} · {m.raw_total} raw
          </div>
          <div className="mt">{m.text}</div>
          {m.raw_sample.slice(0, 4).map((r, i) => (
            <div key={i} className="raw">
              <span className="rs">[{r.source}]</span> {r.content}
            </div>
          ))}
        </div>
      ))}
    </aside>
  );
}
