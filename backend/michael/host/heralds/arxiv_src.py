"""arXiv via its public Atom API: title + abstract of the top matches."""
import re
import xml.etree.ElementTree as ET

from ...models import Source
from .http import clean_query, get

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}


def search(query: str, n: int = 3) -> list[Source]:
    terms = " AND ".join(f"all:{w}" for w in re.findall(r"[A-Za-z0-9]+", clean_query(query))[:8])
    xml = get(API, {"search_query": terms or query, "start": 0, "max_results": n, "sortBy": "relevance"}).text
    out = []
    for e in ET.fromstring(xml).findall("a:entry", NS):
        title = " ".join(e.findtext("a:title", "", NS).split())
        abstract = " ".join(e.findtext("a:summary", "", NS).split())
        url = e.findtext("a:id", "", NS)
        if abstract:
            out.append(Source(kind="arxiv", title=title, url=url, text=f"{title}. {abstract}"))
    return out
