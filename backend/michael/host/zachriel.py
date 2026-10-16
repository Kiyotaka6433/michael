"""Zachriel, the angel of memory: flashcards from verified sentences.

Only sentences the verifier marked SUPPORTED become cards. The LLM writes the question; the answer is the
verified sentence itself, unchanged, followed by the link to its source quote - so every answer stays proven.
Output uses the Obsidian Spaced Repetition plugin's one-line format: `Question::Answer`.
"""
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


def make_cards(facts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """facts: [(verified sentence, source link)] -> [(question, answer with link)]"""
    if not facts:
        return []
    listing = "\n".join(f"{i}. {sentence}" for i, (sentence, _) in enumerate(facts))
    try:
        data = chat_json(SYSTEM, f"Facts:\n{listing}", schema=SCHEMA)
    except Exception:
        return []
    cards, seen = [], set()
    for c in data.get("cards", []):
        i, q = c.get("id"), " ".join(str(c.get("question", "")).split())
        if not isinstance(i, int) or not 0 <= i < len(facts) or i in seen or not q.endswith("?") or len(q) > 220:
            continue
        sentence, link = facts[i]
        if q.rstrip("?").lower() in sentence.lower():          # the question gives the answer away
            continue
        seen.add(i)
        cards.append((q.replace("::", ":"), f"{sentence.replace('::', ':')} ({link})"))
    return cards


def render_deck(title: str, deck_tag: str, cards: list[tuple[str, str]], source_note: str) -> str:
    lines = ["---", "michael: generated", "tags: [flashcards]", "---", f"# Flashcards: {title}", "",
             f"#flashcards/{deck_tag}", "", f"From the verified notes of [[{source_note}]]. "
             "Every answer is a sentence Michael checked against its source quote.", ""]
    lines += [f"{q}::{a}" for q, a in cards]
    return "\n".join(lines) + "\n"
