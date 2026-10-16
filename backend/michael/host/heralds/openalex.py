"""OpenAlex scholarly works (free, no key). Abstracts arrive as an inverted index and are rebuilt here."""
from ...models import Source
from ...config import settings
from .http import clean_query, get

API = "https://api.openalex.org/works"


def rebuild_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    positions = [(pos, word) for word, poss in inverted.items() for pos in poss]
    return " ".join(w for _, w in sorted(positions))


def search(query: str, n: int = 3) -> list[Source]:
    data = get(API, {"search": clean_query(query), "per-page": n, "filter": "has_abstract:true",
                     "mailto": settings.contact}).json()
    out = []
    for w in data.get("results", []):
        abstract = rebuild_abstract(w.get("abstract_inverted_index"))
        if abstract:
            title = w.get("display_name") or "Untitled"
            url = w.get("doi") or w.get("id", "")
            out.append(Source(kind="openalex", title=title, url=url, text=f"{title}. {abstract}"))
    return out
