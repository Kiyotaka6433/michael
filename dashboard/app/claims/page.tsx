import { get } from "../../lib/api";

export const dynamic = "force-dynamic";

type Claim = { path: string; idx: number; sentence: string; status: string; entailment: number | null; quote: string;
  source: string; in_context: number; math: string; rel: string | null; subject: string | null };

const STATUSES = ["", "supported", "partial", "removed"];

export default async function ClaimsPage({ searchParams }: { searchParams: { status?: string; source?: string; q?: string } }) {
  const { status = "", source = "", q = "" } = searchParams;
  const qs = new URLSearchParams({ limit: "200", ...(status && { status }), ...(source && { source }), ...(q && { q }) });
  let data: { claims: Claim[]; totals: Record<string, number> } = { claims: [], totals: {} };
  let error = "";
  try {
    data = await get(`/api/v1/claims?${qs}`);
  } catch {
    error = "Michael's backend is not running.";
  }
  const t = data.totals;
  return (
    <>
      <h1 className="page-title">Every sentence Michael wrote</h1>
      <p className="muted">{t.SUPPORTED ?? 0} verified · {t.PARTIAL ?? 0} partial · {t.REMOVED ?? 0} removed (shown in the notes' “Removed claims”)</p>
      <form className="row search-box" action="/claims">
        <select name="status" defaultValue={status}>{STATUSES.map((s) => <option key={s} value={s}>{s || "any verdict"}</option>)}</select>
        <input name="source" defaultValue={source} placeholder="cited article, e.g. Euclidean algorithm" />
        <input name="q" defaultValue={q} placeholder="words in the sentence" />
        <button>Filter</button>
      </form>
      {error && <div className="card error">{error}</div>}
      {data.claims.map((c) => (
        <div key={`${c.path}-${c.idx}`} className={`claim ${c.status.toLowerCase()}`}>
          <div className="row between">
            <span className={`tag ${c.status.toLowerCase()}`}>{c.status}{c.entailment != null ? ` ${c.entailment.toFixed(2)}` : ""}
              {c.math === "match" ? " · math ✓" : ""}{c.in_context ? " · in context" : ""}</span>
            {c.rel && <a className="muted small" href={`/note?path=${encodeURIComponent(c.rel)}`}>{c.rel.split("/").pop()?.replace(/\.md$/, "")}</a>}
          </div>
          <p className="sentence">{c.sentence}</p>
          {c.quote && <blockquote>{c.quote.slice(0, 400)}{c.quote.length > 400 ? "…" : ""} <span className="muted small">{c.source}</span></blockquote>}
        </div>
      ))}
    </>
  );
}
