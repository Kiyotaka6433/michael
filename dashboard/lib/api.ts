export const API = process.env.NEXT_PUBLIC_MICHAEL_API ?? "http://127.0.0.1:8765";

export type Stats = {
  total: number; drafted: number; supported: number; partial: number; unsupported: number;
  removed: number; sources: number; seconds: number;
};

export type RunSummary = {
  id: string; question: string; model: string; status: string;
  started_at: number; finished_at: number | null; stats: Partial<Stats>;
};

export type Verdict = {
  label: string; evidence_label: string; quote: string; entailment: number; contradiction: number;
};

export type ClaimRow = {
  idx: number; sentence: string; citations: string[]; status: string; rounds: number;
  verdict: Verdict | null; human_label: string | null;
};

export type Evidence = { label: string; kind: string; title: string; url: string; heading: string; text: string; score: number };

export type RunDetail = RunSummary & { markdown: string | null; note_path: string | null; error: string | null;
  evidence: Evidence[]; claims: ClaimRow[] };

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
