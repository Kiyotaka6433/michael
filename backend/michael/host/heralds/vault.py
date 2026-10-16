"""Your Obsidian vault as a source: chunks per heading section, citable as [[Note#Heading]]."""
import re
from pathlib import Path

from ...models import Chunk, sha
from ..scrolls import sentence_spans

SKIP_DIRS = {".obsidian", ".trash", ".git", "Michael"}   # never cite Michael's own output notes
HEADING = re.compile(r"(?m)^(?=#{1,3} )")
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def _pieces(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Split a long section at sentence boundaries into spans of at most max_chars (no text is dropped)."""
    if len(text) <= max_chars:
        return [(0, len(text))]
    out, start, end = [], 0, 0
    for s, e in sentence_spans(text) or [(0, len(text))]:
        if e - start > max_chars and end > start:
            out.append((start, end))
            start = s
        end = e
        while end - start > max_chars:            # one very long "sentence" (e.g. a table): hard split
            out.append((start, start + max_chars))
            start += max_chars
    if end > start:
        out.append((start, end))
    return out


def file_chunks(md: Path, max_chars: int = 1000) -> list[Chunk]:
    text = md.read_text(encoding="utf8", errors="ignore")
    body_offset = m.end() if (m := FRONTMATTER.match(text)) else 0
    out, pos = [], body_offset
    for part in HEADING.split(text[body_offset:]):
        start = pos
        pos += len(part)
        if not part.strip():
            continue
        first = part.splitlines()[0]
        heading = first.lstrip("#").strip() if first.startswith("#") else md.stem
        for s, e in _pieces(part, max_chars):
            if part[s:e].strip():
                out.append(Chunk(source_id=sha(str(md))[:16], kind="vault", title=md.stem, url=str(md),
                                 text=part[s:e], start=start + s, end=start + e, heading=heading))
    return out


def is_generated(md: Path) -> bool:
    """Michael's own answer / key-points notes (frontmatter has `question:`): never evidence for new notes,
    otherwise the writer could end up citing its own earlier output."""
    head = md.read_text(encoding="utf8", errors="ignore")[:600]
    m = FRONTMATTER.match(head)
    return bool(m and re.search(r"(?m)^(question:|michael: )", m.group(0)))   # answers, hubs, flashcards


def vault_chunks(vault_dir: str, max_chars: int = 1000) -> list[Chunk]:
    root = Path(vault_dir)
    out = []
    for md in sorted(root.rglob("*.md")):
        if not any(part in SKIP_DIRS for part in md.relative_to(root).parts) and not is_generated(md):
            out += file_chunks(md, max_chars)
    return out
