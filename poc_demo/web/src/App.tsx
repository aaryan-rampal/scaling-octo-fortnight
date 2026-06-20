import { useEffect, useState } from "react";
import "./App.css";
import { fetchNetworks, type Networks } from "./api";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; data: Networks };

function App() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    fetchNetworks()
      .then((data) => active && setState({ kind: "ready", data }))
      .catch((err: unknown) =>
        active && setState({ kind: "error", message: String(err) }),
      );
    return () => {
      active = false;
    };
  }, []);

  if (state.kind === "loading") {
    return (
      <main className="app">
        <Header bank="…" />
        <p className="status">Booting embedded Hindsight and querying memory…</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="app">
        <Header bank="—" />
        <p className="status error">
          Could not reach the API. Is the backend running on :8000?
          <br />
          <code>{state.message}</code>
        </p>
      </main>
    );
  }

  const d = state.data;
  return (
    <main className="app">
      <Header bank={d.bank_id} />

      <Connections text={d.connections} />

      <div className="grid">
        <Section title="Episodic memory" subtitle="experiences" count={d.episodic.length}>
          {d.episodic.map((e, i) => (
            <li key={i}>
              <span>{e.text}</span>
              {e.when && <time>{e.when}</time>}
            </li>
          ))}
        </Section>

        <Section title="Semantic memory" subtitle="world facts" count={d.semantic.length}>
          {d.semantic.map((s, i) => (
            <li key={i}>
              <span>{s.text}</span>
            </li>
          ))}
        </Section>

        <Section title="People" subtitle="entities" count={d.people.length}>
          {d.people.map((p, i) => (
            <li key={i}>
              <span className="name">{p.name}</span>
              {p.note && <span className="note">{p.note}</span>}
            </li>
          ))}
        </Section>

        <Section
          title="Principles"
          subtitle="evolving beliefs"
          count={d.principles.length}
        >
          {d.principles.length === 0 ? (
            <li className="empty">None surfaced yet — load more episodes.</li>
          ) : (
            d.principles.map((p, i) => (
              <li key={i}>
                <span className="name">{p.name}</span>
                {p.content && <span className="note">{p.content}</span>}
              </li>
            ))
          )}
        </Section>
      </div>
    </main>
  );
}

function Header({ bank }: { bank: string }) {
  return (
    <header className="header">
      <h1>
        recall<span className="dot">.</span>
      </h1>
      <p>
        memory networks from your iMessages · bank <code>{bank}</code>
      </p>
    </header>
  );
}

function Connections({ text }: { text: string }) {
  return (
    <section className="connections">
      <h2>Hindsight connection</h2>
      {text ? (
        <p>{text}</p>
      ) : (
        <p className="empty">No connection synthesized.</p>
      )}
    </section>
  );
}

interface SectionProps {
  title: string;
  subtitle: string;
  count: number;
  children: React.ReactNode;
}

function Section({ title, subtitle, count, children }: SectionProps) {
  return (
    <section className="card">
      <h3>
        {title} <span className="sub">{subtitle}</span>
        <span className="count">{count}</span>
      </h3>
      <ul>{children}</ul>
    </section>
  );
}

export default App;
