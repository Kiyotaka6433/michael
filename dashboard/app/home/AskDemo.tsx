"use client";
// Live "ask": as you type, the facts Michael has already verified that are closest in meaning, with the time taken.
import { useEffect, useState } from "react";
import { API } from "@/lib/api";

type Fact = { fact: string; quote: string; source: string; score: number };
const EXAMPLES = ["Dijkstra's algorithm", "Chinese remainder theorem", "Gradient descent", "Fenwick tree"];

export default function AskDemo() {
  const [q, setQ] = useState("");
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [ms, setMs] = useState(0);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (q.trim().length < 3) { setFacts(null); return; }
    const ctl = new AbortController();
    const id = setTimeout(async () => {
      const t0 = performance.now();
      try {
        const r = await fetch(`${API}/api/v1/facts?k=5&q=${encodeURIComponent(q)}`, { signal: ctl.signal });
        const d = await r.json();
        setMs(Math.round(performance.now() - t0));
        setFacts((d.facts || []).filter((f: Fact) => f.score >= 0.6));
        setErr(false);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setErr(true);
      }
    }, 220);
    return () => { clearTimeout(id); ctl.abort(); };
  }, [q]);

  return (
    <div className="ask">
      <div className="ask-box">
        <span className="ask-icon" aria-hidden="true">⌕</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything you have studied…" aria-label="Ask" />
        {facts && <span className="ask-time">{ms} ms</span>}
      </div>
      <div className="ask-chips">
        {EXAMPLES.map((x) => <button key={x} className="chip" onClick={() => setQ(x)}>{x}</button>)}
      </div>
      {err && <p className="muted">The Michael backend isn't running (michael serve).</p>}
      <div className="ask-results">
        {facts?.length === 0 && <p className="muted">Nothing verified on that yet. Michael can research it for you.</p>}
        {facts?.map((f, i) => (
          <div key={f.fact} className="ask-fact" style={{ animationDelay: `${i * 60}ms` }}>
            <div className="ask-fact-head"><span className="tick">✓</span>{f.fact}</div>
            <blockquote>“{f.quote.length > 240 ? f.quote.slice(0, 240) + "…" : f.quote}”</blockquote>
            <div className="muted">{f.source.replace(/^\[\[|\]\]$/g, "")} · match {Math.round(f.score * 100)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}
