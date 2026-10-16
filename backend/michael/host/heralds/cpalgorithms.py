"""cp-algorithms.com (algorithms for competitive programming, CC BY-SA). The site has no search API, but publishes
its full-text search index; it is downloaded once a week, searched locally with BM25, and the best pages are
fetched with their math intact."""
import json
import time

from rank_bm25 import BM25Okapi

from ...config import settings
from ...models import Source
from ..jophiel import tokenize
from .http import get
from .webmath import fetch as fetch_page

INDEX_URL = "https://cp-algorithms.com/search/search_index.json"
_cache = {"t": 0.0, "docs": None, "bm25": None}


def _index():
    path = settings.data_dir / "cp_algorithms_index.json"
    if _cache["docs"] is None or time.time() - _cache["t"] > 86400:
        if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(get(INDEX_URL).text, encoding="utf8")
        docs = [d for d in json.loads(path.read_text(encoding="utf8"))["docs"]
                if d.get("location") and "#" not in d["location"] and len(d.get("text", "")) > 500]
        _cache.update(t=time.time(), docs=docs, bm25=BM25Okapi([tokenize(d["title"] + " " + d["text"]) for d in docs]))
    return _cache["docs"], _cache["bm25"]


def search(query: str, n: int = 2) -> list[Source]:
    docs, bm25 = _index()
    scores = bm25.get_scores(tokenize(query))
    best = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:n]
    out = []
    for i in best:
        if scores[i] <= 0:
            continue
        url = "https://cp-algorithms.com/" + docs[i]["location"]
        try:
            page = fetch_page(url)
            text = page.markdown
        except Exception:
            text = docs[i]["text"]
        out.append(Source(kind="cpalgorithms", title=f"{docs[i]['title'].replace('¶', '').strip()} (cp-algorithms)", url=url, text=text))
    return out
