"""Local PDFs: one Source per page so citations can say "p. N"."""
from pathlib import Path

import pymupdf as fitz

from ...models import Source


def load(path: str) -> list[Source]:
    out = []
    with fitz.open(path) as doc:
        title = doc.metadata.get("title") or Path(path).stem
        for i, page in enumerate(doc, 1):
            text = page.get_text().strip()
            if text:
                out.append(Source(kind="pdf", title=f"{title}, p. {i}", url=f"{Path(path).resolve()}#page={i}", text=text))
    return out
