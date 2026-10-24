"use client";
// Study mode: multiple-choice questions made from Michael's verified facts (no LLM: a key term is blanked out of a
// verified sentence). After each answer the source quote that proves the fact is shown.
import { useEffect, useState } from "react";
import Markdown from "../Markdown";
import { API } from "../../lib/api";

type Q = { question: string; answer: string; options: string[]; kind: string; fact: string; quote: string; source: string; note: string };

const SUBJECTS = ["", "Number Theory", "DSA and Competitive Programming", "Machine Learning"];

export default function Quiz() {
  const [subject, setSubject] = useState("");
  const [qs, setQs] = useState<Q[] | null>(null);
  const [i, setI] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [score, setScore] = useState(0);
  const [missed, setMissed] = useState<Q[]>([]);
  const [error, setError] = useState("");

  async function load(s = subject) {
    setError(""); setI(0); setPicked(null); setScore(0); setMissed([]);
    try {
      const r = await fetch(`${API}/api/v1/quiz?n=10${s ? `&subject=${encodeURIComponent(s)}` : ""}&seed=${Date.now() % 100000}`);
      setQs((await r.json()).questions);
    } catch {
      setError("Michael's backend is not running.");
    }
  }
  useEffect(() => { load(); }, []);

  function pick(o: string) {
    if (picked) return;
    const q = qs![i];
    setPicked(o);
    if (o === q.answer) setScore((x) => x + 1);
    else setMissed((m) => [...m, q]);
  }

  const q = qs?.[i];
  const source = (s: string) => s.replace(/^\[\[|\]\]$/g, "");
  return (
    <>
      <div className="row between">
        <h1 className="page-title">Quiz</h1>
        <select value={subject} onChange={(e) => { setSubject(e.target.value); load(e.target.value); }}>
          {SUBJECTS.map((s) => <option key={s} value={s}>{s || "All subjects"}</option>)}
        </select>
      </div>
      <p className="muted">Questions are verified facts from your notes with one key term blanked out. Each answer is backed by a source quote.</p>
      {error && <div className="card error">{error}</div>}
      {qs && qs.length === 0 && <div className="card">No verified facts to quiz on yet.</div>}
      {q && (
        <div className="card flashcard">
          <div className="muted small">Question {i + 1} of {qs!.length} · score {score} · {q.note.split(/[\\/]/).pop()?.replace(".md", "")}</div>
          <div className="q"><Markdown text={q.question} /></div>
          <div className="quiz-options">
            {q.options.map((o) => (
              <button key={o} onClick={() => pick(o)}
                className={picked ? (o === q.answer ? "on" : o === picked ? "wrong" : "") : ""}>
                <Markdown text={o} />
              </button>
            ))}
          </div>
          {picked && (
            <>
              <div className="a">
                <div>{picked === q.answer ? "✓ Correct." : "✗ Not quite."} <Markdown text={q.fact} /></div>
                <blockquote className="muted small"><Markdown text={q.quote} /> — {source(q.source)}</blockquote>
              </div>
              <button className="on" onClick={() => { setPicked(null); setI((x) => x + 1); }}>
                {i + 1 < qs!.length ? "Next question" : "See result"}
              </button>
            </>
          )}
        </div>
      )}
      {qs && qs.length > 0 && i >= qs.length && (
        <div className="card">
          <h2>{score} / {qs.length}</h2>
          {missed.length > 0 && <>
            <p className="muted">Review these facts:</p>
            <ul>{missed.map((m) => <li key={m.fact}><Markdown text={m.fact} /> <span className="muted small">({source(m.source)})</span></li>)}</ul>
          </>}
          <button className="on" onClick={() => load()}>New quiz</button>
        </div>
      )}
    </>
  );
}
