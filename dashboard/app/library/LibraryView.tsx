"use client";
import { useEffect, useMemo, useState } from "react";
import { noteHref, type Subject } from "../../lib/library";

function CountUp({ to }: { to: number }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 900);
      setN(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return <>{n.toLocaleString()}</>;
}

export default function LibraryView({ subjects }: { subjects: Subject[] }) {
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<string>("");
  const [openAll, setOpenAll] = useState<boolean | null>(null);

  const totals = useMemo(() => {
    const topics = subjects.flatMap((s) => s.topics);
    return {
      articles: topics.reduce((n, t) => n + t.articles.length, 0),
      topics: topics.length,
      overviews: topics.filter((t) => t.overview).length,
      verified: topics.reduce((n, t) => n + (t.verified || 0), 0),
    };
  }, [subjects]);

  const needle = q.trim().toLowerCase();
  const matches = (s: Subject, t: Subject["topics"][number]) =>
    !needle || t.name.toLowerCase().includes(needle) || s.name.toLowerCase().includes(needle) ||
    t.articles.some((a) => a.title.toLowerCase().includes(needle));
  const shown = subjects.filter((s) => !only || s.name === only)
    .map((s) => ({ s, topics: s.topics.filter((t) => matches(s, t)) }))
    .filter((x) => x.topics.length);

  return (
    <>
      <div className="stat-row">
        <div className="stat"><div className="v"><CountUp to={totals.articles} /></div><div className="l">articles</div></div>
        <div className="stat"><div className="v"><CountUp to={totals.topics} /></div><div className="l">topics</div></div>
        <div className="stat"><div className="v"><CountUp to={totals.overviews} /></div><div className="l">topic overviews</div></div>
        <div className="stat"><div className="v"><CountUp to={totals.verified} /></div><div className="l">verified overview sentences</div></div>
      </div>

      <div className="lib-tools">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter topics and articles…  ( / )"
               aria-label="Filter topics and articles" />
        <button className={`chip${!only ? " on" : ""}`} onClick={() => setOnly("")}>All</button>
        {subjects.map((s) => (
          <button key={s.name} className={`chip${only === s.name ? " on" : ""}`} onClick={() => setOnly(only === s.name ? "" : s.name)}>
            {s.name}
          </button>
        ))}
        <button className="chip" onClick={() => setOpenAll(!openAll)}>{openAll ? "Collapse all" : "Expand all"}</button>
      </div>

      {shown.length === 0 && <div className="card empty-hint muted">Nothing matches “{q}”. Try a shorter word.</div>}

      {shown.map(({ s, topics }) => {
        const articles = s.topics.reduce((n, t) => n + t.articles.length, 0);
        const overviews = s.topics.filter((t) => t.overview).length;
        const links = s.topics.reduce((n, t) => n + t.links.length, 0) + s.inbox.length;
        return (
          <section key={s.name} className={`card subject ${s.tag}`}>
            <h2>{s.name}</h2>
            <p className="muted">{s.intro} · {articles} articles · {overviews} topic overviews · {links} saved links</p>
            <div className="topics">
              {topics.map((t) => (
                <details key={t.name + String(openAll) + needle} className="topic" open={openAll ?? (!!needle || undefined)}>
                  <summary>
                    <b>{t.name}</b>{" "}
                    <span className="muted">
                      {t.articles.length} articles{t.links.length ? ` · ${t.links.length} links` : ""}
                      {t.overview ? ` · overview ${t.verified}/${t.total} verified` : ""}
                    </span>
                  </summary>
                  {t.overview && <p><a href={noteHref(t.overview)} className="overview">Topic overview →</a></p>}
                  <ul className="items">
                    {t.articles.map((a) => (
                      <li key={a.title}>
                        {a.path ? <a href={noteHref(a.path)}>{a.title}</a> : a.title}
                        {a.keypoints && <> · <a href={noteHref(a.keypoints)} className="muted">key points</a></>}
                        {a.formulas ? <span className="muted"> · {a.rendered}/{a.formulas} formulas</span> : null}
                      </li>
                    ))}
                  </ul>
                  {t.links.length > 0 && (
                    <>
                      <p className="muted small">Reading list</p>
                      <ul className="items">{t.links.map((l) => <li key={l.title}>{l.path ? <a href={noteHref(l.path)}>{l.title}</a> : l.title}</li>)}</ul>
                    </>
                  )}
                </details>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}
