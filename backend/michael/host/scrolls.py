"""Sentence splitting and chunking that keep exact character offsets into the source text."""
import re

from ..models import Chunk, Source

_SENT_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")


# lines that are Markdown structure, not prose: each forms a block of its own
_SPECIAL = re.compile(r"[ \t]*(#{1,6} |\$\$|\*Figure|\||>)")


def _blocks(text: str) -> list[tuple[int, int]]:
    """Paragraph blocks: runs of ordinary lines; blank lines end a block, structure lines stand alone."""
    blocks, cur, pos = [], None, 0
    for line in text.splitlines(keepends=True):
        s, e = pos, pos + len(line.rstrip("\r\n"))
        pos += len(line)
        if not line.strip() or _SPECIAL.match(line):
            if cur:
                blocks.append(cur)
            cur = None
            if line.strip():
                blocks.append((s, e))
        else:
            cur = (cur[0], e) if cur else (s, e)
    if cur:
        blocks.append(cur)
    return blocks


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each sentence; whitespace between sentences is excluded.
    Sentences never cross a paragraph break, so a heading is never glued onto the sentence after it."""
    spans = []
    for b_start, b_end in _blocks(text):
        start = b_start
        for m in _SENT_END.finditer(text, b_start, b_end):
            end = m.start() + len(m.group(0).rstrip())
            spans.append((start, end))
            start = m.end()
        if start < b_end:
            spans.append((start, b_end))
    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


def split_sentences(text: str) -> list[str]:
    return [text[s:e] for s, e in sentence_spans(text)]


def chunk_source(src: Source, max_chars: int = 900) -> list[Chunk]:
    """Group whole sentences into chunks of about max_chars, overlapping by one sentence."""
    spans = sentence_spans(src.text)
    chunks, i = [], 0
    while i < len(spans):
        j = i
        while j + 1 < len(spans) and spans[j + 1][1] - spans[i][0] <= max_chars:
            j += 1
        s, e = spans[i][0], spans[j][1]
        chunks.append(Chunk(source_id=src.id, kind=src.kind, title=src.title, url=src.url,
                            text=src.text[s:e], start=s, end=e))
        if j + 1 >= len(spans):
            break
        i = j if j > i else j + 1     # one-sentence overlap
    return chunks
