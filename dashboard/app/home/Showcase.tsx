"use client";
// Filterable topic showcase: sliding tab indicator, live search, grid/list toggle, FLIP re-layout animation,
// spotlight cards, and a slide-in drawer with the topic's details and its already-verified facts.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { API } from "@/lib/api";
import { noteHref, type Subject } from "@/lib/library";
import { spotlight } from "./motion";

type Topic = Subject["topics"][number] & { subject: string };
type Fact = { fact: string; quote: string; source: string; score: number };

export default function Showcase({ subjects }: { subjects: Subject[] }) {
  const topics: Topic[] = useMemo(() => subjects.flatMap((s) => s.topics.map((t) => ({ ...t, subject: s.name }))), [subjects]);
  const tabs = ["All", ...subjects.map((s) => s.name)];
  const [tab, setTab] = useState("All");
  const [q, setQ] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [open, setOpen] = useState<Topic | null>(null);

  const needle = q.trim().toLowerCase();
  const shown = topics.filter((t) => (tab === "All" || t.subject === tab) &&
    (!needle || t.name.toLowerCase().includes(needle) || t.articles.some((a) => a.title.toLowerCase().includes(needle))));

  // ---- sliding tab indicator
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [ind, setInd] = useState({ x: 0, w: 0 });
  useLayoutEffect(() => {
    const el = tabRefs.current[tab];
    if (el) setInd({ x: el.offsetLeft, w: el.offsetWidth });
  }, [tab, subjects]);

  // ---- FLIP: cards glide from their old position to the new one when the filter or view changes
  const cardRefs = useRef(new Map<string, HTMLElement>());
  const last = useRef(new Map<string, DOMRect>());
  useLayoutEffect(() => {
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    cardRefs.current.forEach((el, key) => {
      const prev = last.current.get(key), now = el.getBoundingClientRect();
      if (reduced) return;
      if (!prev) {
        el.animate([{ opacity: 0, transform: "scale(.94)" }, { opacity: 1, transform: "none" }],
                   { duration: 320, easing: "cubic-bezier(.2,.8,.2,1)" });
      } else if (Math.abs(prev.left - now.left) > 1 || Math.abs(prev.top - now.top) > 1) {
        el.animate([{ transform: `translate(${prev.left - now.left}px, ${prev.top - now.top}px)` }, { transform: "none" }],
                   { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" });
      }
    });
    const snap = new Map<string, DOMRect>();
    cardRefs.current.forEach((el, key) => snap.set(key, el.getBoundingClientRect()));
    last.current = snap;
  }, [tab, needle, view]);

  return (
    <div className="showcase">
      <div className="sc-bar">
        <div className="tabs" role="tablist">
          <span className="tab-ind" style={{ transform: `translateX(${ind.x}px)`, width: ind.w }} />
          {tabs.map((t) => (
            <button key={t} ref={(el) => { tabRefs.current[t] = el; }} role="tab" aria-selected={tab === t}
                    className={`tab${tab === t ? " on" : ""}`} onClick={() => setTab(t)}>
              {t === "DSA and Competitive Programming" ? "DSA & CP" : t}
            </button>
          ))}
        </div>
        <div className="sc-tools">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter topics…" aria-label="Filter topics" />
          <div className="seg" role="group" aria-label="View">
            <span className="seg-ind" style={{ transform: view === "grid" ? "none" : "translateX(100%)" }} />
            <button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")} aria-pressed={view === "grid"}>Grid</button>
            <button className={view === "list" ? "on" : ""} onClick={() => setView("list")} aria-pressed={view === "list"}>List</button>
          </div>
        </div>
      </div>

      <p className="sc-count">{shown.length} of {topics.length} topics</p>
      <div className={`sc-grid ${view}`}>
        {shown.map((t) => {
          const pct = t.total ? Math.round((100 * (t.verified ?? 0)) / t.total) : 0;
          const key = t.subject + "/" + t.name;
          return (
            <button key={key} ref={(el) => { if (el) cardRefs.current.set(key, el); else cardRefs.current.delete(key); }}
                    className="sc-card" onMouseMove={spotlight} onClick={() => setOpen(t)}>
              <span className="sc-sub">{t.subject}</span>
              <span className="sc-name">{t.name}</span>
              <span className="sc-meta">{t.articles.length} articles · {t.articles.filter((a) => a.keypoints).length} key-point notes</span>
              <span className="sc-meter" aria-label={`${t.verified} of ${t.total} overview sentences verified`}>
                <span style={{ width: `${pct}%` }} />
              </span>
              <span className="sc-foot">{t.overview ? `${t.verified}/${t.total} verified` : "no overview yet"}<span className="sc-arrow">→</span></span>
            </button>
          );
        })}
        {shown.length === 0 && <p className="muted">Nothing matches “{q}”.</p>}
      </div>

      <Drawer topic={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function Drawer({ topic, onClose }: { topic: Topic | null; onClose: () => void }) {
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [shownTopic, setShownTopic] = useState<Topic | null>(null);

  useEffect(() => {
    if (topic) setShownTopic(topic);                   // keep the content while the drawer slides out
    if (!topic) return;
    setFacts(null);
    fetch(`${API}/api/v1/facts?k=4&q=${encodeURIComponent(topic.name)}`).then((r) => r.json())
      .then((d) => setFacts(d.facts || [])).catch(() => setFacts([]));
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", esc);
    document.body.style.overflow = "hidden";
    return () => { removeEventListener("keydown", esc); document.body.style.overflow = ""; };
  }, [topic, onClose]);

  const t = shownTopic;
  const pct = t && t.total ? (t.verified ?? 0) / t.total : 0;
  return (
    <div className={`drawer-wrap${topic ? " open" : ""}`} aria-hidden={!topic}>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={t?.name}>
        {t && (
          <>
            <div className="dr-head">
              <div>
                <div className="sc-sub">{t.subject}</div>
                <h3>{t.name}</h3>
              </div>
              <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
            </div>

            <div className="dr-stats">
              <svg viewBox="0 0 36 36" className="ring" aria-hidden="true">
                <circle cx="18" cy="18" r="15.9" className="ring-bg" />
                <circle cx="18" cy="18" r="15.9" className="ring-fg" style={{ strokeDasharray: `${pct * 100} 100` }} />
              </svg>
              <div>
                <div className="dr-big">{t.overview ? `${t.verified}/${t.total}` : "—"}</div>
                <div className="muted">overview sentences proven by a quote</div>
                <div className="muted">{t.articles.length} articles · {t.links.length} saved links</div>
              </div>
            </div>

            <div className="dr-actions">
              {t.overview && <a className="btn primary" href={noteHref(t.overview)}>Read the overview</a>}
              <a className="btn" href={`/search?q=${encodeURIComponent(t.name)}`}>Search this topic</a>
              <a className="btn" href="/quiz">Quiz me</a>
            </div>

            <h4>Already verified</h4>
            {facts === null && <div className="skeleton" />}
            {facts?.length === 0 && <p className="muted">No verified facts on this topic yet.</p>}
            {facts?.map((f, i) => (
              <div key={i} className="fact" style={{ animationDelay: `${i * 70}ms` }}>
                <div>✓ {f.fact}</div>
                <div className="muted">{f.source.replace(/^\[\[|\]\]$/g, "")}</div>
              </div>
            ))}

            <h4>Articles</h4>
            <ul className="dr-list">
              {t.articles.map((a) => (
                <li key={a.title}>
                  {a.path ? <a href={noteHref(a.path)}>{a.title}</a> : a.title}
                  {a.keypoints && <a className="muted" href={noteHref(a.keypoints)}> · key points</a>}
                </li>
              ))}
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}
