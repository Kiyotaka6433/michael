"""Repair what text extraction loses in cp-algorithms source notes, from the original page:

  code       indentation restored and marked as C++ (the extractor flattens <pre> blocks)
  headings   the "¶" permalink sign removed
  practice   the article's "Practice Problems" list (dropped by the extractor) added back, with its links
  links      the article's own links to other cp-algorithms articles: those in the library become [[wikilinks]]
             (links the author made: the most reliable edges in the graph); the rest are reported as candidates
             for new library nodes

The article text itself is not reworded; only formatting and the article's own lists/links are restored.

    python scripts/polish_sources.py                 # polish every cp-algorithms note
    python scripts/polish_sources.py --candidates    # also print the most-linked cp pages missing from the library
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urldefrag

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from lxml import html as lhtml                       # noqa: E402
from michael.host.heralds.http import get           # noqa: E402

STATE = ROOT / "library" / "state.json"
CACHE = ROOT / "library" / "html_cache"
LINKS_START, LINKS_END = "<!-- michael:article-links -->", "<!-- /michael:article-links -->"
CP = "https://cp-algorithms.com/"
norm = lambda s: re.sub(r"\s+", "", s)


def page(url: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (re.sub(r"[^\w]+", "_", url.removeprefix(CP)) + ".html")
    if not f.exists():
        f.write_text(get(url).text, encoding="utf8")
    return f.read_text(encoding="utf8")


def parse(url: str):
    doc = lhtml.fromstring(page(url))
    art = (doc.xpath("//article") or [doc])[0]
    code = [p.text_content().rstrip("\n") for p in art.xpath(".//pre")]
    internal, practice = [], []
    for a in art.iter("a"):
        href = a.get("href") or ""
        full = urldefrag(urljoin(url, href))[0]
        if full.startswith(CP) and full.endswith(".html") and full != url and "/tags.html" not in full:
            internal.append((a.text_content().strip(), full))
    h = art.xpath(".//*[self::h2 or self::h3][starts-with(@id,'practice-problems')]")
    if h:
        for el in h[0].itersiblings():
            if el.tag in ("h2", "h3") or re.search(r"Contributors", el.text_content()[:200]):
                break
            if el.tag not in ("ul", "ol"):
                continue
            for li in el.xpath("./li"):
                a = li.find(".//a")
                if a is not None and "github.com" in (a.get("href") or ""):
                    continue
                text = " ".join(li.text_content().split())
                practice.append(f"- [{text}]({a.get('href')})" if a is not None and a.get("href") else f"- {text}")
    return code, internal, practice


def fix_code(md: str, code: list[str]) -> tuple[str, int]:
    pool = {norm(c): c for c in code}
    fixed = 0

    def repl(m):
        nonlocal fixed
        original = pool.get(norm(m.group(2)))
        if original is None:
            return m.group(0)
        fixed += 1
        lang = m.group(1).strip() or ("cpp" if re.search(r"[;{}]|#include|\bint\b", original) else "")
        return f"```{lang}\n{original}\n```"
    return re.sub(r"```([^\n`]*)\n(.*?)\n?```", repl, md, flags=re.S), fixed


def polish(path: Path, url: str, by_url: dict[str, str]):
    code, internal, practice = parse(url)
    text = path.read_text(encoding="utf8")
    head, sep, tail = text.partition("<!-- michael:")
    head, n_code = fix_code(head, code)
    head = re.sub(r"(?m)^(#{1,6} .*?)\s*¶\s*$", r"\1", head)
    added_practice = False
    if practice and not re.search(r"(?mi)^#{2,3} Practice Problems", head):
        head = head.rstrip() + "\n\n## Practice Problems\n\n" + "\n".join(practice) + "\n\n"
        added_practice = True
    text = head + sep + tail
    # the article's own links to other library articles
    seen, links, missing = set(), [], []
    for anchor, full in internal:
        if full in seen:
            continue
        seen.add(full)
        if full in by_url and by_url[full] != path.stem:
            links.append(f"- [[{by_url[full]}]]" + (f" ({anchor})" if anchor and anchor.lower() not in by_url[full].lower() else ""))
        elif full not in by_url:
            missing.append(full)
    text = re.sub(r"\n?" + re.escape(LINKS_START) + r".*?" + re.escape(LINKS_END) + r"\n?", "\n", text, flags=re.S)
    if links:
        block = f"{LINKS_START}\n## Linked in the article\n" + "\n".join(links) + f"\n{LINKS_END}\n"
        if "<!-- michael:" in text:                      # before the Related / Mentions blocks
            i = text.index("<!-- michael:")
            text = text[:i].rstrip() + "\n\n" + block + "\n" + text[i:]
        else:
            text = text.rstrip() + "\n\n" + block
    path.write_text(text.rstrip() + "\n", encoding="utf8")
    return n_code, len(code), added_practice, len(links), missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    state = json.loads(STATE.read_text(encoding="utf8"))
    saved = {k: v for k, v in state.items() if isinstance(v, dict) and v.get("status") == "saved"}
    by_url = {v["url"]: Path(v["path"]).stem for v in saved.values() if v.get("url")}
    totals, wanted = Counter(), Counter()
    for item, st in sorted(saved.items()):
        if not item.startswith("cp:") or not Path(st["path"]).exists():
            continue
        try:
            n_code, n_pre, practice, n_links, missing = polish(Path(st["path"]), st["url"], by_url)
        except Exception as e:
            print(f"  ! {item}: {e}")
            continue
        totals.update(notes=1, code=n_code, pre=n_pre, practice=practice, links=n_links)
        wanted.update(missing)
        print(f"{item:55s} code {n_code}/{n_pre}  practice {'+' if practice else '-'}  links {n_links}")
    print(dict(totals))
    if a.candidates:
        print("\nmost-linked cp pages not in the library:")
        for url, n in wanted.most_common(60):
            print(f"{n:3d}  {url}")


if __name__ == "__main__":
    main()
