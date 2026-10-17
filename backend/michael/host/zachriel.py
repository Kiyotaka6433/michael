"""Zachriel, the angel of memory: flashcards from verified sentences.

Only sentences the verifier marked SUPPORTED become cards. The LLM writes the question; the answer is the
verified sentence itself, unchanged, followed by the link to its source quote - so every answer stays proven.
Output uses the Obsidian Spaced Repetition plugin's one-line format: `Question::Answer`.
"""
import re

from ..llm import chat_json

SYSTEM = """Turn each fact into one short flashcard question whose answer is exactly that fact.
The question must be answerable from the fact alone, must not contain the answer, and must end with "?".
Keep LaTeX math as it is ($...$).
Return JSON: {"cards": [{"id": 0, "question": "..."}]}"""

SCHEMA = {
    "type": "object",
    "properties": {"cards": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "question": {"type": "string"}},
        "required": ["id", "question"]}}},
    "required": ["cards"],
}


def _ask(facts: list[tuple[str, str]], ids: list[int]) -> dict[int, str]:
    """One question per listed fact. The schema demands exactly len(ids) cards: without it the model often
    stops after the first one (7 verified facts gave 1 card)."""
    listing = "\n".join(f"{i}. {facts[i][0]}" for i in ids)
    schema = {**SCHEMA, "properties": {"cards": {**SCHEMA["properties"]["cards"],
                                                 "minItems": len(ids), "maxItems": len(ids)}}}
    try:
        data = chat_json(SYSTEM + f"\nWrite exactly {len(ids)} cards, one for each fact, using the fact's number as id.",
                         f"Facts:\n{listing}", schema=schema)
    except Exception:
        return {}
    out = {}
    for c in data.get("cards", []):
        i, q = c.get("id"), " ".join(str(c.get("question", "")).split())
        if isinstance(i, int) and i in ids and i not in out and q.endswith("?") and len(q) <= 220 \
                and q.rstrip("?").lower() not in facts[i][0].lower():          # a question that gives the answer away
            out[i] = q
    return out


def make_cards(facts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """facts: [(verified sentence, source link)] -> [(question, answer with link)], one card per fact.
    Facts the model skipped get a second, smaller request."""
    if not facts:
        return []
    questions = _ask(facts, list(range(len(facts))))
    missing = [i for i in range(len(facts)) if i not in questions]
    if missing:
        questions.update(_ask(facts, missing))
    return [(questions[i].replace("::", ":"), f"{facts[i][0].replace('::', ':')} ({facts[i][1]})")
            for i in range(len(facts)) if i in questions]


_FOOT = re.compile(r'^\[\^(\d+)\]: ".*" - (\[\[.*?\]\]|\[.*?\]\(.*?\)) · supported', re.M)
_SENT = re.compile(r"(==)?((?:[^\[\n]|\[(?!\^))+?)(==)?\[\^(\d+)\]")


def facts_from_note(markdown: str) -> list[tuple[str, str]]:
    """The fully verified sentences of a Michael note (not the highlighted PARTIAL ones), each with the link of
    its supporting quote - so decks can be rebuilt from notes that already exist."""
    links = {m.group(1): m.group(2) for m in _FOOT.finditer(markdown)}
    body = markdown.split("> Verifier:", 1)[-1].split("\n## ", 1)[0]
    out = []
    for m in _SENT.finditer(body):
        sentence = m.group(2).strip().lstrip("⚠✗ ").strip()
        if not m.group(1) and m.group(4) in links and sentence:
            out.append((sentence, links[m.group(4)]))
    return out


def keep_schedules(old_deck: str, new_deck: str) -> str:
    """Carry Spaced Repetition review history (<!--SR:...-->) over to the regenerated deck, matched by answer."""
    sr = {}
    for line in old_deck.splitlines():
        if "::" in line and (m := re.search(r"\s*(<!--SR:.*?-->)\s*$", line)):
            sr[line[: m.start()].split("::", 1)[1].strip()] = m.group(1)
    out = []
    for line in new_deck.splitlines():
        if "::" in line and (key := line.split("::", 1)[1].strip()) in sr:
            line = f"{line} {sr[key]}"
        out.append(line)
    return "\n".join(out) + "\n"


def render_deck(title: str, deck_tag: str, cards: list[tuple[str, str]], source_note: str) -> str:
    lines = ["---", "michael: generated", "tags: [flashcards]", "---", f"# Flashcards: {title}", "",
             f"#flashcards/{deck_tag}", "", f"From the verified notes of [[{source_note}]]. "
             "Every answer is a sentence Michael checked against its source quote.", ""]
    lines += [f"{q}::{a}" for q, a in cards]
    return "\n".join(lines) + "\n"
