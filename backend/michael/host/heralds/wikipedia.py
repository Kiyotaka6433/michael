"""Wikipedia via the public MediaWiki API (no key needed)."""
from ...models import Source
from .http import clean_query, get

API = "https://en.wikipedia.org/w/api.php"


def search(query: str, n: int = 3) -> list[Source]:
    hits = get(API, {"action": "query", "list": "search", "srsearch": clean_query(query), "srlimit": n,
                     "format": "json"}).json()["query"]["search"]
    if not hits:
        return []
    titles = "|".join(h["title"] for h in hits)
    pages = get(API, {"action": "query", "prop": "extracts|info", "inprop": "url", "explaintext": 1,
                      "titles": titles, "format": "json", "redirects": 1}).json()["query"]["pages"]
    out = []
    for p in pages.values():
        text = p.get("extract", "")
        if text:
            out.append(Source(kind="wikipedia", title=p["title"], url=p.get("fullurl", ""), text=text))
    return out
