"""Find the exact span (1-3 consecutive sentences) of a chunk that best matches a claim."""
import re

import numpy as np
from rapidfuzz import fuzz

from .scrolls import sentence_spans

# Markdown structure is never quoted as evidence: headings, figure placeholders, table rows, callouts
NOT_PROSE = re.compile(r"^(#{1,6} |\*Figure|\||>\s*\[!|---)")


def _strip_marker(text: str, s: int, e: int) -> tuple[int, int]:
    """A sentence on a callout line starts with '> ': quote it without the marker."""
    while s < e and text[s] == ">":
        s += 1
        while s < e and text[s] == " ":
            s += 1
    return s, e


def paragraph_of(text: str, s: int, e: int, max_chars: int = 1500) -> tuple[int, int]:
    """The paragraph (text between blank lines / line breaks) around a span, capped at max_chars."""
    ps = text.rfind("\n", 0, s) + 1
    pe = text.find("\n", e)
    pe = len(text) if pe == -1 else pe
    ps, pe = _strip_marker(text, ps, pe)
    if pe - ps > max_chars:                       # keep the span, centred, inside the cap
        ps = max(ps, min(s, e - max_chars // 2) - max_chars // 2)
        pe = min(pe, ps + max_chars)
    return ps, pe


def candidate_windows(text: str, max_len: int = 3) -> list[tuple[int, int]]:
    spans = [_strip_marker(text, s, e) for s, e in sentence_spans(text) if not NOT_PROSE.match(text[s:e])]
    spans = [(s, e) for s, e in spans if e > s] or [(0, len(text))]
    out = []
    for i in range(len(spans)):
        for k in range(1, max_len + 1):
            if i + k <= len(spans):
                window = (spans[i][0], spans[i + k - 1][1])
                if k > 1 and "\n\n" in text[window[0]:window[1]]:
                    break                        # windows stay inside one paragraph
                out.append(window)
    return out


def _semantic(claim: str, texts: list[str]) -> np.ndarray | None:
    """Cosine similarity of the claim to each window (bge-small, cached); None if the embedder is unavailable."""
    try:
        from .archangel import EMBEDDER
        from ..models import Chunk
        vecs = EMBEDDER.chunks([Chunk(source_id="", kind="", title="", url="", text=t, start=0, end=len(t))
                                for t in texts])
        return vecs @ EMBEDDER.encode([claim])[0]
    except Exception:
        return None


def lexical_candidates(claim: str, text: str, top: int = 5, semantic: bool | None = None) -> list[tuple[int, int]]:
    """Top windows for the NLI judge: ranked by word overlap AND by meaning (embedding similarity), merged, so a
    paraphrased claim still reaches the sentence that proves it. Shorter windows win ties so quotes stay tight."""
    wins = candidate_windows(text)
    lexical = sorted(wins, key=lambda w: (fuzz.token_set_ratio(claim, text[w[0]:w[1]]), -(w[1] - w[0])), reverse=True)
    if semantic is None:
        from ..config import settings
        semantic = settings.semantic_windows
    if not semantic or len(wins) <= top:
        return lexical[:top]
    sims = _semantic(claim, [text[s:e] for s, e in wins])
    if sims is None:
        return lexical[:top]
    by_meaning = [wins[i] for i in np.argsort(-sims)]
    out = []
    for pair in zip(lexical, by_meaning):           # interleave the two rankings, best of each first
        for w in pair:
            if w not in out:
                out.append(w)
        if len(out) >= top:
            break
    return out[:top]
