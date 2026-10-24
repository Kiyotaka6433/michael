"use client";
// Coverage map: per topic, which source articles back verified facts (and which are saved but unused).
import { Fragment, useEffect, useState } from "react";
import { API } from "../../lib/api";

type Source = { title: string; note: string; kind: string; verified_facts: number; key_points: boolean };
type Topic = { topic: string; overview_verified: number; thin: boolean; sources: Source[]; unused_sources: number; covered_pct: number };
type Cov = { subjects: { subject: string; topics: Topic[] }[];
             summary: { sources: number; cited_by_verified_facts: number; with_key_points: number; thin_topics: string[] } };

export default function Coverage() {
  const [cov, setCov] = useState<Cov | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${API}/api/v1/coverage`).then((r) => r.json()).then(setCov).catch(() => setError("Michael's backend is not running."));
  }, []);
  const s = cov?.summary;
  return (
    <>
      <h1 className="page-title">Coverage</h1>
      <p className="muted">Which saved articles actually back verified facts. Unused articles are where key points or a richer overview would add the most.</p>
      {error && <div className="card error">{error}</div>}
      {s && <div className="card">
        <b>{s.cited_by_verified_facts}</b> of {s.sources} articles back at least one verified fact ·{" "}
        <b>{s.with_key_points}</b> have key points · {s.thin_topics.length ? `thin topics: ${s.thin_topics.join(", ")}` : "no thin topic overviews"}
      </div>}
      {cov?.subjects.map((su) => (
        <div key={su.subject} className="card">
          <h2>{su.subject}</h2>
          <table className="coverage">
            <thead><tr><th>Topic</th><th>Overview</th><th>Articles used</th><th></th></tr></thead>
            <tbody>
              {su.topics.map((t) => {
                const id = `${su.subject}/${t.topic}`;
                return (
                  <Fragment key={id}>
                    <tr onClick={() => setOpen(open === id ? null : id)} className="clickable">
                      <td>{t.topic}</td>
                      <td className={t.thin ? "warn" : ""}>{t.overview_verified} verified</td>
                      <td><div className="bar"><span style={{ width: `${t.covered_pct}%` }} /></div></td>
                      <td className="muted small">{t.sources.length - t.unused_sources}/{t.sources.length}</td>
                    </tr>
                    {open === id && (
                      <tr><td colSpan={4}>
                        <ul className="sources">
                          {[...t.sources].sort((a, b) => b.verified_facts - a.verified_facts).map((x) => (
                            <li key={x.note} className={x.verified_facts ? "" : "muted"}>
                              <a href={`/note?path=${encodeURIComponent(`${su.subject}/Sources/${x.note}.md`)}`}>{x.title}</a>
                              {" · "}{x.verified_facts} verified fact{x.verified_facts === 1 ? "" : "s"}{x.key_points ? " · key points" : ""}
                            </li>
                          ))}
                        </ul>
                      </td></tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}
