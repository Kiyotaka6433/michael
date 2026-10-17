"""The data that makes Michael better with use: claims of every generated note, flashcard reviews, and the
right/wrong labels that calibrate the verifier.

  index_note_claims(path, text)    every sentence of a Michael note -> note_claims (verdict, quote, source, math)
  query_claims(...)                e.g. all PARTIAL sentences, or every sentence citing one article
  log_review(...) / review_stats() flashcard review history: today, last 7 days, streak, retention
  import_gold() / calibrate()      labels -> the lowest support threshold that keeps precision >= the target
"""
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db
from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS note_claims (
    path TEXT, idx INTEGER, sentence TEXT, status TEXT, entailment REAL, quote TEXT, source TEXT,
    in_context INTEGER, math TEXT, PRIMARY KEY (path, idx)
);
CREATE INDEX IF NOT EXISTS note_claims_status ON note_claims(status);
CREATE INDEX IF NOT EXISTS note_claims_source ON note_claims(source);
CREATE TABLE IF NOT EXISTS card_reviews (
    ts REAL, day TEXT, deck TEXT, question TEXT, grade TEXT, interval INTEGER, ease INTEGER, was_new INTEGER
);
CREATE TABLE IF NOT EXISTS gold_labels (
    id TEXT PRIMARY KEY, note TEXT, sentence TEXT, system TEXT, entailment REAL, label TEXT, reason TEXT, labeler TEXT
);
"""

FOOT = re.compile(r'^\[\^(\d+)\]: "(.*)" - (\[\[.*?\]\]|\[.*?\]\(.*?\)) · (\w+)(.*?)\(entailment ([\d.]+)\)', re.M)
SENT = re.compile(r"(==)?((?:[^\[\n]|\[(?!\^))+?)(==)?\[\^(\d+)\]")


def init():
    with db.connect() as con:
        con.executescript(SCHEMA)


# ------------------------------------------------------------------ claims of generated notes
def parse_note_claims(text: str) -> list[dict]:
    feet = {m.group(1): m for m in FOOT.finditer(text)}
    body = text.split("> Verifier:", 1)[-1].split("\n## ", 1)[0]
    rows = []
    for m in SENT.finditer(body):
        f = feet.get(m.group(4))
        tail = f.group(5) if f else ""
        rows.append({"sentence": m.group(2).strip().lstrip("⚠✗ ").strip().strip("="),
                     "status": f.group(4).upper() if f else "UNKNOWN", "entailment": float(f.group(6)) if f else None,
                     "quote": f.group(2) if f else "", "source": f.group(3) if f else "",
                     "in_context": int("in the context" in tail),
                     "math": "match" if "formulas and numbers checked" in tail else ""})
    removed = text.split("## Removed claims", 1)
    if len(removed) == 2:
        for s in re.findall(r"^- ~~(.*)~~$", removed[1].split("\n## ", 1)[0], re.M):
            rows.append({"sentence": s, "status": "REMOVED", "entailment": None, "quote": "", "source": "",
                         "in_context": 0, "math": ""})
    return rows


def index_note_claims(path: str, text: str):
    init()
    rows = parse_note_claims(text) if re.search(r"(?m)^question:", text[:600]) else []
    with db.connect() as con:
        con.execute("DELETE FROM note_claims WHERE path=?", (path,))
        con.executemany("INSERT INTO note_claims VALUES (?,?,?,?,?,?,?,?,?)",
                        [(path, i, r["sentence"], r["status"], r["entailment"], r["quote"], r["source"],
                          r["in_context"], r["math"]) for i, r in enumerate(rows)])
    return len(rows)


def query_claims(status: str | None = None, source: str | None = None, subject: str | None = None,
                 q: str | None = None, limit: int = 100) -> list[dict]:
    init()
    where, params = ["1=1"], []
    if status:
        where.append("c.status = ?"); params.append(status.upper())
    if source:
        where.append("c.source LIKE ?"); params.append(f"%[[{source}%")
    if q:
        where.append("c.sentence LIKE ?"); params.append(f"%{q}%")
    if subject:
        where.append("n.subject = ?"); params.append(subject)
    with db.connect() as con:
        rows = con.execute(f"SELECT c.*, n.rel, n.subject FROM note_claims c LEFT JOIN vault_notes n ON n.path = c.path "
                           f"WHERE {' AND '.join(where)} ORDER BY c.path, c.idx LIMIT ?", [*params, limit]).fetchall()
        totals = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) n FROM note_claims GROUP BY status")}
    return {"claims": [dict(r) for r in rows], "totals": totals}


# ------------------------------------------------------------------ flashcard reviews
def log_review(deck: str, question: str, grade: str, interval: int, ease: int, was_new: bool):
    init()
    with db.connect() as con:
        con.execute("INSERT INTO card_reviews VALUES (?,?,?,?,?,?,?,?)",
                    (time.time(), date.today().isoformat(), deck, question, grade, interval, ease, int(was_new)))


def review_stats(today: date | None = None) -> dict:
    init()
    today = today or date.today()
    with db.connect() as con:
        days = {r["day"]: r["n"] for r in con.execute("SELECT day, COUNT(*) n FROM card_reviews GROUP BY day")}
        recall = con.execute("SELECT grade FROM card_reviews WHERE was_new = 0").fetchall()
        decks = con.execute("SELECT deck, COUNT(*) n, AVG(grade != 'hard') ok FROM card_reviews GROUP BY deck "
                            "ORDER BY ok ASC LIMIT 5").fetchall()
    streak, d = 0, today
    while days.get(d.isoformat()):
        streak, d = streak + 1, d - timedelta(days=1)
    week = [{"day": (today - timedelta(days=i)).isoformat(), "reviews": days.get((today - timedelta(days=i)).isoformat(), 0)}
            for i in range(6, -1, -1)]
    retention = round(100 * sum(r["grade"] != "hard" for r in recall) / len(recall), 1) if recall else None
    return {"today": days.get(today.isoformat(), 0), "streak_days": streak, "last_7_days": week,
            "total_reviews": sum(days.values()), "retention_pct": retention,
            "weakest_decks": [{"deck": r["deck"], "reviews": r["n"], "ok_pct": round(100 * (r["ok"] or 0), 1)} for r in decks]}


# ------------------------------------------------------------------ labels and calibration
def import_gold(gold_dir: Path) -> int:
    """Load eval/gold labels (with the system verdict and entailment of each sentence) into the database."""
    init()
    cands = {json.loads(l)["id"]: json.loads(l) for l in (gold_dir / "candidates.jsonl").read_text(encoding="utf8").splitlines() if l.strip()}
    labels = [json.loads(l) for l in (gold_dir / "gold.jsonl").read_text(encoding="utf8").splitlines() if l.strip()]
    rows = [(g["id"], cands[g["id"]]["note"], cands[g["id"]]["sentence"], cands[g["id"]]["system"],
             cands[g["id"]].get("entailment"), g["label"], g.get("reason", ""), g.get("labeler", ""))
            for g in labels if g["id"] in cands]
    with db.connect() as con:
        con.executemany("INSERT OR REPLACE INTO gold_labels VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def calibrate(target_precision: float = 0.95, strict: bool = True) -> dict:
    """Lowest entailment threshold whose verified sentences reach the target precision on the labels.
    Only sentences the verifier scored (SUPPORTED / PARTIAL) carry an entailment, so this tunes the cut-off
    between those two; it never lowers it below the configured partial threshold."""
    init()
    with db.connect() as con:
        rows = con.execute("SELECT entailment, label FROM gold_labels WHERE entailment IS NOT NULL").fetchall()
    good = (lambda l: l == "correct") if strict else (lambda l: l != "wrong")
    table = []
    for t in [round(x / 100, 2) for x in range(40, 100, 5)]:
        kept = [r for r in rows if r["entailment"] >= t]
        if kept:
            table.append({"threshold": t, "kept": len(kept), "precision": round(sum(good(r["label"]) for r in kept) / len(kept), 4)})
    ok = [r for r in table if r["precision"] >= target_precision]
    best = min(ok, key=lambda r: r["threshold"]) if ok else None
    return {"labels": len(rows), "target": target_precision, "strict": strict, "current": settings.support_threshold,
            "recommended": best["threshold"] if best else None, "table": table}
