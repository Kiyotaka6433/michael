import { library, noteHref, type Subject } from "../../lib/library";

export const dynamic = "force-dynamic";

export default async function LibraryPage() {
  let subjects: Subject[] = [];
  let error = "";
  try {
    subjects = await library();
  } catch (e) {
    error = "Michael's backend is not running. Start it from Obsidian or with: michael serve";
  }
  if (error) return <div className="card error">{error}</div>;

  return (
    <>
      <div className="row between">
        <h1 className="page-title">Library</h1>
        <form action="/search" className="row"><input name="q" placeholder="Search every note…" /><button>Search</button></form>
      </div>
      {subjects.map((s) => {
        const articles = s.topics.reduce((n, t) => n + t.articles.length, 0);
        const overviews = s.topics.filter((t) => t.overview).length;
        const links = s.topics.reduce((n, t) => n + t.links.length, 0) + s.inbox.length;
        return (
          <section key={s.name} className={`card subject ${s.tag}`}>
            <h2>{s.name}</h2>
            <p className="muted">{s.intro} · {articles} articles · {overviews} topic overviews · {links} saved links</p>
            <div className="topics">
              {s.topics.map((t) => (
                <details key={t.name} className="topic">
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
