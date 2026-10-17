import { noteHref, search, type SearchHit } from "../../lib/library";

export const dynamic = "force-dynamic";

const KIND: Record<string, string> = { source: "article", topic: "topic overview", keypoints: "key points", note: "your note" };

export default async function SearchPage({ searchParams }: { searchParams: { q?: string } }) {
  const q = (searchParams.q ?? "").trim();
  let hits: SearchHit[] = [];
  let error = "";
  if (q) {
    try {
      hits = (await search(q)).results;
    } catch {
      error = "Michael's backend is not running.";
    }
  }
  return (
    <>
      <form action="/search" className="row search-box">
        <input name="q" defaultValue={q} placeholder="e.g. modular inverse, segment tree lazy propagation, dropout" autoFocus />
        <button>Search</button>
      </form>
      {error && <div className="card error">{error}</div>}
      {q && !error && <p className="muted">{hits.length} passages · full-text and meaning search over the whole vault</p>}
      {hits.map((h) => (
        <a key={h.id} href={noteHref(h.rel, h.heading)} className="card hit">
          <div className="row between">
            <b>{h.title}</b>
            <span className="muted small">{h.subject} · {KIND[h.kind] ?? h.kind}</span>
          </div>
          {h.heading && h.heading !== h.title && <div className="muted small">§ {h.heading.replace(/¶/g, "")}</div>}
          <p className="small">{h.text.replace(/^#+ [^\n]*\n/, "").replace(/[¶#*`]/g, "").replace(/\s+/g, " ").slice(0, 280)}…</p>
        </a>
      ))}
    </>
  );
}
