"""Semantic Scholar academic graph (free, no key; shared rate limit, so it is throttled to ~1 request/s).
Returns paper abstracts, preferring well-cited papers, with the open-access link when there is one."""
from ...models import Source
from .http import clean_query, get

API = "https://api.semanticscholar.org/graph/v1/paper/search"


def search(query: str, n: int = 3) -> list[Source]:
    data = get(API, {"query": clean_query(query), "limit": n * 2,
                     "fields": "title,abstract,year,citationCount,url,openAccessPdf,externalIds"}).json()
    papers = [p for p in data.get("data", []) if p.get("abstract")]
    papers.sort(key=lambda p: p.get("citationCount") or 0, reverse=True)
    out = []
    for p in papers[:n]:
        ids = p.get("externalIds") or {}
        url = (f"https://arxiv.org/abs/{ids['ArXiv']}" if ids.get("ArXiv")
               else (p.get("openAccessPdf") or {}).get("url") or p.get("url", ""))
        title = f"{p['title']} ({p.get('year', 'n.d.')}, {p.get('citationCount', 0)} citations)"
        out.append(Source(kind="semanticscholar", title=title, url=url, text=f"{p['title']}. {p['abstract']}"))
    return out
