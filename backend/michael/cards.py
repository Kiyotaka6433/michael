"""Flashcard review shared with Obsidian's Spaced Repetition plugin.

Decks are the vault's Flashcards/*.md notes with one card per line: `Question::Answer`. After a review the plugin
appends its schedule to the line as `<!--SR:!YYYY-MM-DD,interval,ease-->`; this module reads and writes exactly that,
so a card reviewed in the web app is up to date in Obsidian and the other way round. The file always wins: a review
is only written if the card's line still says what the reviewer saw.
"""
import re
from datetime import date, timedelta
from pathlib import Path

CARD = re.compile(r"^(?P<q>.+?)::(?P<a>.+?)(?:\s*<!--SR:!(?P<due>\d{4}-\d{2}-\d{2}),(?P<ivl>\d+),(?P<ease>\d+)-->)?\s*$")
DEFAULT_EASE = 250


def decks(vault: Path) -> list[Path]:
    return sorted(p for p in vault.rglob("Flashcards/*.md") if ".trash" not in p.parts)


def parse(path: Path) -> list[dict]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf8", errors="ignore").splitlines()):
        if "::" not in line or line.startswith(("#", ">")):
            continue
        m = CARD.match(line)
        if m:
            out.append({"line": i, "question": m["q"].strip(), "answer": m["a"].strip(), "due": m["due"],
                        "interval": int(m["ivl"]) if m["ivl"] else 0, "ease": int(m["ease"]) if m["ease"] else DEFAULT_EASE})
    return out


def due_cards(vault: Path, subject: str | None = None, today: date | None = None, limit: int = 50) -> dict:
    today = today or date.today()
    due, new, total = [], [], 0
    for deck in decks(vault):
        rel = deck.relative_to(vault).as_posix()
        if subject and not rel.startswith(subject + "/"):
            continue
        for c in parse(deck):
            total += 1
            card = {**c, "deck": rel, "subject": rel.split("/")[0]}
            if not c["due"]:
                new.append(card)
            elif date.fromisoformat(c["due"]) <= today:
                due.append(card)
    due.sort(key=lambda c: c["due"])
    cards = (due + new)[:limit]
    return {"cards": cards, "due": len(due), "new": len(new), "total": total}


def schedule(interval: int, ease: int, grade: str, is_new: bool) -> tuple[int, int]:
    """SM-2 as the Spaced Repetition plugin does it: ease starts at 250 (%), easy +20, hard -20 (min 130)."""
    if grade == "easy":
        ease += 20
        interval = 4 if is_new else round(max(interval, 1) * ease / 100 * 1.3)
    elif grade == "good":
        interval = 1 if is_new else round(max(interval, 1) * ease / 100)
    else:                                     # hard
        ease = max(130, ease - 20)
        interval = 1 if is_new else max(1, round(interval * 0.5))
    return max(1, interval), ease


def review(vault: Path, deck_rel: str, line: int, question: str, grade: str, today: date | None = None) -> dict:
    if grade not in ("easy", "good", "hard"):
        raise ValueError("grade must be easy, good or hard")
    deck = (vault / deck_rel).resolve()
    if vault.resolve() not in deck.parents or not deck.exists():
        raise FileNotFoundError(deck_rel)
    lines = deck.read_text(encoding="utf8").split("\n")
    m = CARD.match(lines[line]) if 0 <= line < len(lines) else None
    if not m or m["q"].strip() != question:
        raise LookupError("the card changed in the vault since it was shown")   # the file wins
    is_new = not m["due"]
    interval, ease = schedule(int(m["ivl"] or 0), int(m["ease"] or DEFAULT_EASE), grade, is_new)
    due = (today or date.today()) + timedelta(days=interval)
    base = re.sub(r"\s*<!--SR:.*?-->\s*$", "", lines[line])
    lines[line] = f"{base} <!--SR:!{due.isoformat()},{interval},{ease}-->"
    deck.write_text("\n".join(lines), encoding="utf8")
    return {"due": due.isoformat(), "interval": interval, "ease": ease, "was_new": is_new}
