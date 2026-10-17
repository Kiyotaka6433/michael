import Markdown from "../Markdown";
import { note, noteHref, type Note } from "../../lib/library";

export const dynamic = "force-dynamic";

export default async function NotePage({ searchParams }: { searchParams: { path?: string } }) {
  const path = searchParams.path ?? "";
  let n: Note | null = null;
  try {
    n = await note(path);
  } catch {
    return <div className="card error">Note not found: {path}</div>;
  }
  const fm = n.frontmatter;
  return (
    <div className="note-layout">
      <article className="card note">
        <div className="row between note-head">
          <span className="muted small">{n.path}</span>
          <span className="row">
            {fm.url && <a className="btn" href={fm.url} target="_blank" rel="noreferrer">Original ↗</a>}
            <a className="btn primary" href={n.obsidian}>Open in Obsidian</a>
          </span>
        </div>
        {(fm.extraction || fm.formulas) && (
          <p className="muted small">
            {fm.extraction && <>Extracted via <b>{fm.extraction}</b></>}
            {fm.formulas && <> · {fm.formulas_rendered ?? "?"}/{fm.formulas} formulas render</>}
          </p>
        )}
        <Markdown text={n.markdown} />
      </article>
      <aside className="card side">
        <h3>Linked from</h3>
        {n.backlinks.length === 0 && <p className="muted small">No other notes link here yet.</p>}
        <ul className="items">
          {n.backlinks.slice(0, 40).map((b) => (
            <li key={b}><a href={noteHref(b)}>{b.split("/").pop()?.replace(/\.md$/, "")}</a></li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
