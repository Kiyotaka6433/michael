"""Flashcards: parsing and writing the Spaced Repetition plugin's format, SM-2 scheduling, file-wins rule."""
from datetime import date

import pytest

from michael import cards

DECK = """---
michael: generated
---
# Flashcards: Modular arithmetic

#flashcards/number-theory

What is the modulus?::The value at which numbers wrap around. ([[Modular arithmetic]])
When does an inverse exist?::When a and m are coprime. <!--SR:!2026-10-10,3,250-->
"""


def _vault(tmp_path):
    d = tmp_path / "Number Theory" / "Flashcards"
    d.mkdir(parents=True)
    (d / "Modular arithmetic - cards.md").write_text(DECK, encoding="utf8")
    return tmp_path


def test_due_and_new_cards_are_listed(tmp_path):
    out = cards.due_cards(_vault(tmp_path), today=date(2026, 10, 17))
    assert (out["due"], out["new"], out["total"]) == (1, 1, 2)
    assert out["cards"][0]["question"] == "When does an inverse exist?"       # overdue first


def test_review_writes_the_plugin_format_and_keeps_the_text(tmp_path):
    v = _vault(tmp_path)
    deck = "Number Theory/Flashcards/Modular arithmetic - cards.md"
    r = cards.review(v, deck, 8, "When does an inverse exist?", "good", today=date(2026, 10, 17))
    assert r == {"due": "2026-10-25", "interval": 8, "ease": 250}             # 3 days x 2.5
    line = (v / deck).read_text(encoding="utf8").split("\n")[8]
    assert line == "When does an inverse exist?::When a and m are coprime. <!--SR:!2026-10-25,8,250-->"
    r = cards.review(v, deck, 7, "What is the modulus?", "easy", today=date(2026, 10, 17))
    assert r["interval"] == 4 and r["ease"] == 270


def test_a_card_edited_in_obsidian_is_not_overwritten(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(LookupError):
        cards.review(v, "Number Theory/Flashcards/Modular arithmetic - cards.md", 7, "Some old question?", "good")
