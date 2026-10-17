"use client";
// Flashcard review in the browser (or on the phone). Reads and writes the same <!--SR:...--> schedule as the
// Obsidian Spaced Repetition plugin, so reviews count in both places.
import { useEffect, useState } from "react";
import Markdown from "../Markdown";
import { API } from "../../lib/api";

type Card = { deck: string; subject: string; line: number; question: string; answer: string; due: string | null; interval: number };
type Queue = { cards: Card[]; due: number; new: number; total: number };

const SUBJECTS = ["", "Number Theory", "DSA and Competitive Programming", "Machine Learning"];

export default function Flashcards() {
  const [subject, setSubject] = useState("");
  const [queue, setQueue] = useState<Queue | null>(null);
  const [i, setI] = useState(0);
  const [shown, setShown] = useState(false);
  const [done, setDone] = useState(0);
  const [error, setError] = useState("");
  const [stats, setStats] = useState<{ today: number; streak_days: number; retention_pct: number | null; total_reviews: number } | null>(null);

  async function load(s = subject) {
    setError(""); setI(0); setShown(false);
    try {
      const r = await fetch(`${API}/api/v1/flashcards?limit=40${s ? `&subject=${encodeURIComponent(s)}` : ""}`);
      setQueue(await r.json());
      setStats(await (await fetch(`${API}/api/v1/flashcards/stats`)).json());
    } catch {
      setError("Michael's backend is not running.");
    }
  }
  useEffect(() => { load(); }, []);

  async function grade(g: "hard" | "good" | "easy") {
    const c = queue!.cards[i];
    const r = await fetch(`${API}/api/v1/flashcards/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deck: c.deck, line: c.line, question: c.question, grade: g }),
    });
    if (r.status === 409) setError("This card was edited in Obsidian - skipped.");
    setDone((d) => d + 1); setShown(false); setI((x) => x + 1);
  }

  const card = queue?.cards[i];
  return (
    <>
      <div className="row between">
        <h1 className="page-title">Flashcards</h1>
        <select value={subject} onChange={(e) => { setSubject(e.target.value); load(e.target.value); }}>
          {SUBJECTS.map((s) => <option key={s} value={s}>{s || "All subjects"}</option>)}
        </select>
      </div>
      {queue && <p className="muted">{queue.due} due · {queue.new} new · {queue.total} cards · {done} reviewed this session ·
        every answer is a sentence Michael verified against its source</p>}
      {stats && <p className="muted small">{stats.today} reviewed today · {stats.streak_days}-day streak · {stats.total_reviews} reviews in all{stats.retention_pct != null ? ` · ${stats.retention_pct}% recalled` : ""}</p>}
      {error && <div className="card error">{error}</div>}
      {queue && !card && <div className="card">Nothing left to review. <button onClick={() => load()}>Check again</button></div>}
      {card && (
        <div className="card flashcard">
          <div className="muted small">{card.subject} · {card.deck.split("/").pop()?.replace(" - cards.md", "")}</div>
          <div className="q"><Markdown text={card.question} /></div>
          {shown ? (
            <>
              <div className="a"><Markdown text={card.answer} /></div>
              <div className="row">
                <button onClick={() => grade("hard")}>Hard</button>
                <button onClick={() => grade("good")} className="on">Good</button>
                <button onClick={() => grade("easy")}>Easy</button>
              </div>
            </>
          ) : (
            <button className="on" onClick={() => setShown(true)}>Show answer</button>
          )}
        </div>
      )}
    </>
  );
}
