"use client";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { API, get, post, RunSummary } from "@/lib/api";

type Event = { stage: string; detail: string; t: number };

export default function Home() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [log, setLog] = useState<Event[]>([]);
  const [busy, setBusy] = useState(false);

  const load = () => get<RunSummary[]>("/runs").then(setRuns).catch(() => setError(`Backend not reachable at ${API}. Run: michael serve`));
  useEffect(() => { load(); }, []);

  async function start() {
    if (!question.trim()) return;
    setBusy(true);
    setLog([]);
    const { run_id } = await post<{ run_id: string }>("/research", { question });
    const es = new EventSource(`${API}/runs/${run_id}/events`);
    const stages = ["queued", "plan", "vault", "gather", "search", "rerank", "write", "verify", "repair", "warn", "done", "error"];
    stages.forEach((s) => es.addEventListener(s, (ev) => {
      const data = (ev as MessageEvent).data;
      if (!data) { es.close(); setBusy(false); return; }
      const e: Event = JSON.parse(data);
      setLog((l) => [...l, e]);
      if (e.stage === "done" || e.stage === "error") { es.close(); setBusy(false); load(); }
    }));
  }

  const chart = runs.filter((r) => r.status === "done").slice(0, 12).reverse().map((r, i) => ({
    run: `#${i + 1}`, verified: r.stats.supported ?? 0, partial: r.stats.partial ?? 0, removed: r.stats.removed ?? 0,
  }));
  const done = runs.filter((r) => r.status === "done");
  const totals = done.reduce((a, r) => ({ s: a.s + (r.stats.supported ?? 0), t: a.t + (r.stats.drafted ?? 0) }), { s: 0, t: 0 });

  return (
    <>
      <section className="card">
        <h2>New research run</h2>
        <div className="row">
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="How does LACP differ from PAgP?"
                 onKeyDown={(e) => e.key === "Enter" && start()} />
          <button onClick={start} disabled={busy}>{busy ? "Running…" : "Research"}</button>
        </div>
        {log.length > 0 && <ol className="log">{log.map((e, i) => <li key={i}><b>{e.stage}</b> {e.detail} <span className="muted">{e.t}s</span></li>)}</ol>}
      </section>

      {error && <p className="error">{error}</p>}

      <section className="grid">
        <div className="card kpi"><div className="v">{done.length}</div><div className="muted">completed runs</div></div>
        <div className="card kpi"><div className="v">{totals.t ? Math.round((100 * totals.s) / totals.t) : 0}%</div><div className="muted">drafted sentences verified</div></div>
        <div className="card kpi"><div className="v">{done.reduce((a, r) => a + (r.stats.removed ?? 0), 0)}</div><div className="muted">unsupported claims removed</div></div>
      </section>

      {chart.length > 0 && (
        <section className="card">
          <h2>Verification per run</h2>
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="run" /><YAxis allowDecimals={false} /><Tooltip /><Legend />
                <Bar dataKey="verified" stackId="a" fill="#2f6b3a" />
                <Bar dataKey="partial" stackId="a" fill="#b08d57" />
                <Bar dataKey="removed" stackId="a" fill="#a23b2a" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <section className="card">
        <h2>Runs</h2>
        <table>
          <thead><tr><th>Question</th><th>Status</th><th>Verified</th><th>Removed</th><th>Time</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td><a href={`/runs/${r.id}`}>{r.question}</a></td>
                <td>{r.status}</td>
                <td>{r.stats.supported ?? "-"}/{r.stats.total ?? "-"}</td>
                <td>{r.stats.removed ?? "-"}</td>
                <td>{r.stats.seconds ? `${r.stats.seconds}s` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
