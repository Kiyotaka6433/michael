"""Any URL you add yourself: main text extracted with trafilatura."""
import trafilatura

from ...models import Source
from .http import get


def fetch(url: str) -> Source | None:
    html = get(url).text
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else url)
    return Source(kind="web", title=title, url=url, text=text) if text else None
