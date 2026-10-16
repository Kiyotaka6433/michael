"""arXiv papers from the author's own LaTeX source, converted to Markdown by pandoc, so every formula is exact.

Steps: arXiv id -> metadata (arXiv API) -> e-print archive (safe extract into a temp folder) -> main .tex file
-> flatten \\input / \\include and local macro files -> pandoc (sandboxed) -> clean Markdown with $...$ math.
"""
import gzip
import io
import re
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ...config import settings
from .http import get

NEW_ID = r"\d{4}\.\d{4,5}(?:v\d+)?"
OLD_ID = r"[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
MAX_ARCHIVE = 200 * 1024 * 1024


@dataclass
class Article:
    title: str
    url: str
    markdown: str
    route: str                      # arxiv-latex | web-math | web | pdf-text
    authors: list = field(default_factory=list)
    date: str = ""
    abstract: str = ""
    notes: list = field(default_factory=list)   # warnings about the extraction


def parse_arxiv_id(s: str) -> str | None:
    s = s.strip()
    m = re.search(rf"arxiv\.org/(?:abs|pdf|html|e-print)/({NEW_ID}|{OLD_ID})", s)
    if m:
        return m.group(1)
    m = re.fullmatch(rf"(?:arxiv:)?({NEW_ID}|{OLD_ID})", s, re.I)
    return m.group(1) if m else None


def metadata(arxiv_id: str) -> dict:
    """Title, authors, date, abstract: from the arXiv API, or from the abstract page's citation meta tags when
    the API (export.arxiv.org) is slow or unreachable."""
    try:
        return _api_metadata(arxiv_id)
    except Exception:
        return abs_page_metadata(arxiv_id)


def abs_page_metadata(arxiv_id: str) -> dict:
    from lxml import html as lhtml
    doc = lhtml.fromstring(get(f"https://arxiv.org/abs/{arxiv_id}").text)
    meta = lambda name: [m.get("content", "") for m in doc.xpath(f'//meta[@name="{name}"]')]
    title = (meta("citation_title") or [""])[0]
    if not title:
        return {}
    authors = [", ".join(reversed(a.split(", ", 1))) if ", " in a else a for a in meta("citation_author")]
    return {"title": " ".join(title.split()), "authors": authors,
            "date": (meta("citation_date") or [""])[0].replace("/", "-"),
            "abstract": " ".join((meta("citation_abstract") or [""])[0].split())}


def _api_metadata(arxiv_id: str) -> dict:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    r = get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id})
    entry = ET.fromstring(r.text).find("a:entry", ns)
    if entry is None or entry.find("a:title", ns) is None:
        return {}
    text = lambda tag: " ".join((entry.findtext(f"a:{tag}", "", ns) or "").split())
    return {"title": text("title"), "abstract": text("summary"), "date": text("published")[:10],
            "authors": [a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)]}


def _extract(data: bytes, dest: Path):
    """The e-print is a gzipped tar, a gzipped single .tex, or (when no source exists) a PDF."""
    if data[:4] == b"%PDF":
        raise ValueError("this paper has no LaTeX source on arXiv (PDF only)")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            if sum(m.size for m in tar.getmembers()) > MAX_ARCHIVE:
                raise ValueError("source archive is too large")
            tar.extractall(dest, filter="data")          # 'data' filter blocks absolute paths, .., links out
            return
    except tarfile.ReadError:
        pass
    raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
    (dest / "main.tex").write_bytes(raw)


def _main_tex(root: Path) -> Path:
    cands = [p for p in root.rglob("*.tex") if "\\documentclass" in p.read_text("utf8", "ignore")]
    if not cands:
        raise ValueError("no main .tex file found in the source")
    pref = lambda p: ("\\begin{document}" in p.read_text("utf8", "ignore"),
                      p.stem.lower() in ("main", "ms", "paper", "article"), p.stat().st_size)
    return max(cands, key=pref)


MACRO_LINE = re.compile(r"^\s*\\(?:re)?newcommand|^\s*\\DeclareMathOperator|^\s*\\def\\[A-Za-z]+")


def _is_macro(line: str) -> bool:
    """A complete one-line macro definition (balanced braces, no internal @ names)."""
    body = re.sub(r"\\[{}]", "", line)
    return bool(MACRO_LINE.match(line)) and "@" not in line and body.count("{") == body.count("}") > 0


def _flatten(path: Path, root: Path, depth=0) -> str:
    """Inline \\input/\\include files (only from inside the source folder) and the macro definitions of local
    .sty files, so pandoc sees the whole paper and can expand the author's macros."""
    text = path.read_text("utf8", "ignore")
    text = re.sub(r"(?<!\\)%.*", "", text)              # comments (keeps \%)

    def inline(m):
        name = m.group(1).strip()
        f = (path.parent / name)
        f = f if f.suffix == ".tex" else f.with_suffix(f.suffix + ".tex") if f.suffix else f.with_suffix(".tex")
        if not f.exists():
            f = root / Path(name).with_suffix(".tex")
        try:
            f.resolve().relative_to(root.resolve())
        except ValueError:
            return ""
        return _flatten(f, root, depth + 1) if f.exists() and depth < 10 else ""

    text = re.sub(r"\\(?:input|include)\{([^}]+)\}", inline, text)

    def sty(m):
        defs = []
        for name in m.group(1).split(","):
            f = root / f"{name.strip()}.sty"
            if f.exists():
                defs += [l for l in f.read_text("utf8", "ignore").splitlines() if _is_macro(l)]
        return m.group(0) + ("\n" + "\n".join(defs) if defs else "")

    return re.sub(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}", sty, text)


def _pandoc(tex: str, cwd: Path) -> str:
    fmt_out = ("markdown-raw_html-raw_tex-raw_attribute-bracketed_spans-native_divs-native_spans-fenced_divs"
               "-header_attributes-link_attributes-inline_code_attributes-citations-smart-grid_tables"
               "-multiline_tables-simple_tables-implicit_figures")
    r = subprocess.run([settings.pandoc, "--sandbox", "-f", "latex", "-t", fmt_out, "--wrap=none"],
                       input=tex, capture_output=True, text=True, encoding="utf8", cwd=cwd, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"pandoc failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _minimal_preamble(tex: str) -> str:
    """Fallback: keep only the author's math macros from the preamble, drop everything else before the body."""
    head, sep, body = tex.partition("\\begin{document}")
    if not sep:
        return tex
    macros = [l for l in head.splitlines() if _is_macro(l)]
    meta = re.findall(r"\\title(?:\[[^\]]*\])?\{.*?\}", head, re.S)[:1]
    return "\\documentclass{article}\n" + "\n".join(macros + meta) + "\n\\begin{document}" + body


def convert(tex: str, cwd: Path) -> tuple[str, list]:
    """pandoc with the full preamble; if that fails, with a minimal one; then with macros dropped too."""
    notes = []
    for attempt, src in enumerate((tex, _minimal_preamble(tex),
                                   re.sub(r"(?m)^.*\\(?:re)?newcommand.*$", "", _minimal_preamble(tex)))):
        try:
            return _pandoc(src, cwd), notes
        except RuntimeError as e:
            notes.append(f"pandoc attempt {attempt + 1} failed: {str(e)[:160]}")
    raise RuntimeError("pandoc could not convert this paper: " + " | ".join(notes))


def clean_markdown(md: str) -> str:
    md = re.sub(r"!\[([^\]]*)\]\([^)]*\)",                                  # figures: keep real captions only
                lambda m: f"*Figure: {m.group(1)}*" if m.group(1).strip().lower() not in ("", "image") else "", md)
    md = re.sub(r"(?m)(?<!\\)\\$", "", md)       # pandoc hard line breaks (a single "\" at line end; "\\" is math)
    md = re.sub(r"\[\\?\[([^\]]+?)\\?\]\]\(#[^)]*\)", r"(\1)", md)     # [\[eq:1\]](#eq:1) -> (eq:1)
    md = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", md)                  # internal anchors -> plain text
    md = re.sub(r"\\\[@?([^\]]+)\\\]", r"[\1]", md)                    # \[key\] citations -> [key]
    md = re.sub(r"\$\$\s*\n?(.+?)\n?\s*\$\$", lambda m: "$$" + m.group(1).strip() + "$$", md, flags=re.S)
    md = re.sub(r"(?m)^(\$\$.+?\$\$)$", r"\n\1\n", md, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def fetch(arxiv_id: str) -> Article:
    meta = {}
    notes = []
    try:
        meta = metadata(arxiv_id)
    except Exception as e:
        notes.append(f"arXiv metadata unavailable ({e}); title taken from the LaTeX")
    data = get(f"https://arxiv.org/e-print/{arxiv_id}").content
    with tempfile.TemporaryDirectory(prefix="michael-arxiv-") as tmp:
        root = Path(tmp)
        _extract(data, root)
        main = _main_tex(root)
        tex = _flatten(main, root)
        raw, conv_notes = convert(tex, main.parent)
        notes += conv_notes
        md = clean_markdown(raw)
    if len(md) < 2000:     # e.g. a wrapper .tex that only \includepdf's the real paper
        raise ValueError(f"the LaTeX source converted to only {len(md)} characters (wrapper around a PDF?)")
    title = meta.get("title") or (re.search(r"\\title(?:\[[^\]]*\])?\{(.+?)\}", tex, re.S) or [None, arxiv_id])[1]
    return Article(title=" ".join(title.split()), url=f"https://arxiv.org/abs/{arxiv_id}", markdown=md,
                   route="arxiv-latex", authors=meta.get("authors", []), date=meta.get("date", ""),
                   abstract=meta.get("abstract", ""), notes=notes)
