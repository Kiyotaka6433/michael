"""Web articles with their math intact.

Rendered math on web pages keeps its LaTeX source somewhere: MathML `alttext` (Wikipedia, arXiv HTML/LaTeXML),
`<annotation encoding="application/x-tex">` (KaTeX, MathML), or `<script type="math/tex">` (MathJax 2).
Each formula is swapped for a placeholder word before text extraction (extractors mangle or drop math), then
restored as $...$ / $$...$$.
"""
import re

import trafilatura
from lxml import html as lhtml

from .arxiv_latex import Article
from .http import get

TOKEN = "MICHAELMATH{}X"


def _tex_of(el) -> tuple[str | None, bool]:
    """(LaTeX, is_display) for a math element, or (None, False)."""
    ann = el.xpath('.//*[local-name()="annotation"][contains(@encoding, "tex")]')
    # the HTML parser can cut annotation text short (e.g. at "\sigma :"), so take the longest copy available
    copies = [el.get("alttext"), "".join(ann[0].itertext()) if ann else None, el.text if el.tag == "script" else None]
    tex = max((c for c in copies if c and c.strip()), key=len, default=None)
    if not tex:
        return None, False
    display = (el.get("display") == "block" or "display" in (el.get("type") or "")
               or "katex-display" in (el.get("class") or "") or "mwe-math-display" in (el.getparent().get("class") or ""))
    tex = " ".join(tex.split())          # newlines inside inline math break $...$ in Markdown
    if "$" in tex and "\\text" in tex:   # LaTeXML: \text{3$\times$3} -> \text{3}\times\text{3}
        tex = re.sub(r"\$([^$]*)\$", lambda m: "}" + m.group(1) + "\\text{", tex)
    m = re.fullmatch(r"\{\\displaystyle\s*(.*)\}", tex, re.S)      # Wikipedia wraps everything in {\displaystyle ...}
    if m:
        tex = m.group(1).strip()
    m = re.fullmatch(r"\{\\textstyle\s*(.*)\}", tex, re.S)
    if m:
        tex = m.group(1).strip()
    return tex, display


DELIMITED = [(re.compile(r"\A\$\$(.+)\$\$\Z", re.S), True), (re.compile(r"\A\\\[(.+)\\\]\Z", re.S), True),
             (re.compile(r"\A\$(.+)\$\Z", re.S), False), (re.compile(r"\A\\\((.+)\\\)\Z", re.S), False)]


def _delimited(el) -> tuple[str | None, bool]:
    """Math kept as delimited TeX text: MkDocs arithmatex (cp-algorithms) and Sphinx (scikit-learn, d2l.ai)."""
    text = (el.text_content() or "").strip()
    for rx, display in DELIMITED:
        if m := rx.match(text):
            return " ".join(m.group(1).split()) if not display else m.group(1).strip(), display or el.tag == "div"
    return None, False


def _equation_table(table) -> str | None:
    """LaTeXML (arXiv HTML) renders align/eqnarray as a table with one <math> per cell; rebuild it as one
    aligned block: 'lhs &= rhs \\\\ &= more'. Equation-number and padding cells are dropped."""
    rows = []
    for tr in table.xpath('.//tr'):
        cells = []
        for td in tr.xpath('./td'):
            cls = td.get("class") or ""
            if "ltx_eqn_cell" not in cls or "eqno" in cls or "pad" in cls:
                continue
            maths = [t for t in (_tex_of(m)[0] for m in td.xpath('.//*[local-name()="math"]')) if t]
            cells.append(" ".join(re.sub(r"^\\displaystyle\s*", "", t) for t in maths))
        if any(cells):
            rows.append(cells[0] + (" &" + " ".join(cells[1:]) if len(cells) > 1 else ""))
    if not rows:
        return None
    return "\\begin{aligned}" + " \\\\ ".join(rows) + "\\end{aligned}" if len(rows) > 1 or "&" in rows[0] else rows[0]


def protect_math(page: str) -> tuple[str, dict]:
    """Replace every formula with a placeholder word; returns (html, {token: markdown_math})."""
    doc = lhtml.fromstring(page)
    found = {}
    for table in doc.xpath('//table[contains(@class, "ltx_equationgroup") or contains(@class, "ltx_eqn_table")]'):
        if table.getparent() is None or table.xpath('ancestor::table[contains(@class, "ltx_eqn")]'):
            continue
        tex = _equation_table(table)
        if not tex:
            continue
        token = TOKEN.format(len(found))
        found[token] = f"$${tex}$$"
        repl = lhtml.Element("p")
        repl.text, repl.tail = f" {token} ", table.tail
        table.getparent().replace(table, repl)
    for el in doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " arithmatex ")]'
                        ' | //span[contains(concat(" ", normalize-space(@class), " "), " math ")]'
                        ' | //div[contains(concat(" ", normalize-space(@class), " "), " math ")]'):
        if el.getparent() is None:
            continue
        tex, display = _delimited(el)
        if not tex:
            continue
        token = TOKEN.format(len(found))
        found[token] = f"$${tex}$$" if display else f"${tex}$"
        repl = lhtml.Element("p" if display else "span")
        repl.text, repl.tail = f" {token} ", el.tail
        el.getparent().replace(el, repl)
    # outermost wrappers first, so a KaTeX span and its inner <math> become one formula
    selectors = ['//span[contains(@class,"katex-display")]', '//span[contains(@class,"katex")]',
                 '//span[contains(@class,"mwe-math-element")]', '//script[starts-with(@type,"math/tex")]',
                 '//*[local-name()="math"]']
    for sel in selectors:
        for el in doc.xpath(sel):
            if el.getparent() is None:
                continue
            target = el
            if sel.startswith('//span[contains(@class,"mwe'):
                inner = el.xpath('.//*[local-name()="math"]')
                if not inner:
                    continue
                tex, display = _tex_of(inner[0])
                display = display or el.xpath('boolean(ancestor-or-self::*[contains(@class,"mwe-math-display")])')
            else:
                tex, display = _tex_of(el)
            if not tex:
                continue
            token = TOKEN.format(len(found))
            found[token] = f"$${tex}$$" if display else f"${tex}$"
            tail = target.tail or ""
            parent = target.getparent()
            repl = lhtml.Element("p" if display else "span")
            repl.text = f" {token} "
            repl.tail = tail
            parent.replace(target, repl)
    # MathJax 2 renders a preview next to its <script>; drop leftovers so formulas are not duplicated
    for el in doc.xpath('//span[contains(@class,"MathJax_Preview")] | //span[contains(@class,"MathJax")]'
                        ' | //img[contains(@class,"mwe-math-fallback")]'):
        if el.getparent() is not None:
            el.getparent().remove(el)
    return lhtml.tostring(doc, encoding="unicode"), found


def restore_math(text: str, found: dict) -> str:
    for token, math in found.items():
        if math.startswith("$$"):
            text = re.sub(rf"\s*{token}\s*", lambda _: f"\n\n{math}\n\n", text)   # lambda: no escape parsing
        else:
            text = text.replace(token, math)
    text = re.sub(r"(?m)^\s*\\\[edit\\\]\s*$\n?", "", text)                  # Wikipedia section [edit] links
    text = re.sub(r"<sup>.*?</sup>", "", text)                               # footnote markers [1], : 184
    text = re.sub(r" {2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _authors(url: str, meta) -> list:
    if "wikipedia.org" in url:
        return ["Wikipedia contributors"]
    a = (meta.author or "") if meta else ""
    # page chrome mistaken for an author (navigation boxes, "Authority control", long junk)
    return [a] if a and len(a) < 80 and not re.search(r"authority control|navigation|menu", a, re.I) else []


def fetch(url: str) -> Article:
    page = get(url).text
    protected, found = protect_math(page)
    md = trafilatura.extract(protected, output_format="markdown", include_formatting=True, include_links=False,
                             include_tables=True, include_comments=False, favor_recall=True) or ""
    if not md.strip():
        raise ValueError("could not extract the article text from this page")
    md = restore_math(md, found)
    missing = [t for t in found if t not in md and found[t] not in md]
    meta = trafilatura.extract_metadata(page)
    notes = [] if found else ["no LaTeX math found on the page (formulas drawn as images cannot be recovered)"]
    lost = sum(1 for t in found if found[t] not in md)
    if lost:
        notes.append(f"{lost} of {len(found)} formulas were in parts of the page the extractor skipped")
    return Article(title=(meta.title if meta and meta.title else url), url=url, markdown=md.strip(),
                   route="web-math" if found else "web",
                   authors=_authors(url, meta), date=(meta.date or "") if meta else "",
                   notes=notes)
