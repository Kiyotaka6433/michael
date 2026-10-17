"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { get, post, RunDetail } from "@/lib/api";
import Markdown from "../../Markdown";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [err, setErr] = useState("");

  const load = () => get<RunDetail>(`/runs/${id}`).then(setRun).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, [id]);

  async function label(idx: number, human: "supported" | "unsupported") {
    await post(`/runs/${id}/claims/${idx}/label`, { human_label: human });
    load();
  }

  if (err) return <p className="error">{err}</p>;
  if (!run) return <p className="muted">Loading…</p>;
  const ev = Object.fromEntries(run.evidence.map((e) => [e.label, e]));

  return (
    <>
      <section className="card">
        <h2>{run.question}</h2>
        <p className="muted">{run.model} · {run.status} · {run.stats.supported ?? 0}/{run.stats.total ?? 0} verified · {run.stats.removed ?? 0} removed · {run.stats.seconds ?? "-"}s</p>
        {run.error && <p className="error">{run.error}</p>}
        <p className="muted">Mark each verdict right or wrong. Your labels feed <code>python eval/run_eval.py citations</code>.</p>
      </section>

      <section className="card">
        <h2>Claims</h2>
        {run.claims.map((c) => (
          <div key={c.idx} className={`claim ${c.status.toLowerCase()}`}>
            <div className="row between">
              <span className={`tag ${c.status.toLowerCase()}`}>{c.status}</span>
              <span className="muted">{c.verdict ? `entailment ${c.verdict.entailment.toFixed(2)}` : ""}</span>
            </div>
            <p className="sentence">{c.sentence}</p>
            {c.verdict?.quote && (
              <blockquote>
                “{c.verdict.quote}” — {ev[c.verdict.evidence_label] ? <a href={ev[c.verdict.evidence_label].url} target="_blank">{ev[c.verdict.evidence_label].title}</a> : c.verdict.evidence_label}
              </blockquote>
            )}
            <div className="row">
              <span className="muted">Is this sentence really supported by the quote?</span>
              <button className={c.human_label === "supported" ? "on" : ""} onClick={() => label(c.idx, "supported")}>Yes</button>
              <button className={c.human_label === "unsupported" ? "on" : ""} onClick={() => label(c.idx, "unsupported")}>No</button>
            </div>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>Evidence (after reranking)</h2>
        {run.evidence.map((e) => (
          <details key={e.label}>
            <summary><b>[{e.label}]</b> {e.kind}: {e.title}{e.heading ? ` · ${e.heading}` : ""} <span className="muted">score {e.score.toFixed(3)}</span></summary>
            <p className="small">{e.text}</p>
          </details>
        ))}
      </section>

      {run.markdown && (
        <section className="card">
          <h2>Obsidian note</h2>
          <Markdown text={run.markdown.replace(/^---\n[\s\S]*?\n---\n/, "")} />
          <details><summary className="muted small">Markdown source</summary><pre className="md">{run.markdown}</pre></details>
        </section>
      )}
    </>
  );
}
