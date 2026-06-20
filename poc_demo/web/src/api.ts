// Typed client for the Recall demo API (FastAPI backend on :8000, proxied via /api).

export interface EpisodicItem {
  text: string;
  when: string;
}

export interface SemanticItem {
  text: string;
}

export interface PersonItem {
  name: string;
  note: string;
}

export interface PrincipleItem {
  name: string;
  content: string;
}

export interface Networks {
  bank_id: string;
  episodic: EpisodicItem[];
  semantic: SemanticItem[];
  people: PersonItem[];
  principles: PrincipleItem[];
  connections: string;
}

export interface Health {
  status: string;
  bank: string;
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error(`health ${res.status}`);
  return (await res.json()) as Health;
}

export async function fetchNetworks(bank?: string): Promise<Networks> {
  const url = bank ? `/api/networks?bank=${encodeURIComponent(bank)}` : "/api/networks";
  const res = await fetch(url);
  if (!res.ok) throw new Error(`networks ${res.status}`);
  return (await res.json()) as Networks;
}
