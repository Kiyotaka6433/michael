"""Stack Exchange Q&A (Mathematics, Computer Science, Cross Validated, Stack Overflow) via the public API.

Only well-received answers are used: accepted, or score >= MIN_SCORE. The source text is the question title plus
the answer, with the site's $...$ LaTeX kept as written. No key needed (300 requests/day per IP; results are
cached for 7 days like every other source).
"""
import html
import re

from lxml import html as lhtml

from ...models import Source
from .http import clean_query, get

API = "https://api.stackexchange.com/2.3"
SITES = ("math", "cs", "stats", "stackoverflow")
MIN_SCORE = 3


def _text(body_html: str) -> str:
    doc = lhtml.fromstring(f"<div>{body_html}</div>")
    for code in doc.xpath("//pre"):                       # keep code blocks readable
        code.text = "\n" + (code.text_content() or "") + "\n"
        for child in list(code):
            code.remove(child)
    return html.unescape(re.sub(r"\n{3,}", "\n\n", doc.text_content())).strip()


def search_site(query: str, site: str, n: int = 2) -> list[Source]:
    qs = get(f"{API}/search/advanced", {"q": clean_query(query), "site": site, "sort": "relevance", "order": "desc",
                                        "answers": 1, "pagesize": n * 2, "filter": "default"}).json().get("items", [])
    qs = [q for q in qs if q.get("is_answered")][:n]
    if not qs:
        return []
    ids = ";".join(str(q["question_id"]) for q in qs)
    answers = get(f"{API}/questions/{ids}/answers", {"site": site, "sort": "votes", "order": "desc",
                                                     "filter": "withbody", "pagesize": 30}).json().get("items", [])
    best = {}
    for a in answers:
        if (a.get("is_accepted") or a.get("score", 0) >= MIN_SCORE) and a["question_id"] not in best:
            best[a["question_id"]] = a
    out = []
    for q in qs:
        a = best.get(q["question_id"])
        if not a:
            continue
        title = html.unescape(q["title"])
        text = f"{title}\n\n{_text(a['body'])}"
        votes = f"{a.get('score', 0)} votes{', accepted' if a.get('is_accepted') else ''}"
        host = "stackoverflow.com" if site == "stackoverflow" else f"{site}.stackexchange.com"
        out.append(Source(kind="stackexchange", title=f"{title} ({host}, {votes})",
                          url=f"https://{host}/a/{a['answer_id']}", text=text))
    return out


def search(query: str, n: int = 3) -> list[Source]:
    out = []
    for site in SITES:
        try:
            out += search_site(query, site, n=1 if site == "stackoverflow" else 2)
        except Exception:
            continue
    return out[: n + 2]
