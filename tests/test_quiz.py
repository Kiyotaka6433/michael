"""Study-mode quiz from verified facts: whole-word blanks, same-kind distractors, the answer is among the options."""
from michael import learning, quiz

FACTS = [
    {"sentence": "Underfitting happens when a model is too simplistic.", "path": "a.md", "quote": "q", "source": "[[A]]"},
    {"sentence": "Overfitting happens when a model memorises training data.", "path": "a.md", "quote": "q", "source": "[[A]]"},
    {"sentence": "Regularization penalises large weights in a model.", "path": "a.md", "quote": "q", "source": "[[A]]"},
    {"sentence": "Dropout randomly disables neurons during training.", "path": "a.md", "quote": "q", "source": "[[A]]"},
    {"sentence": "Gradient descent minimises a differentiable loss function.", "path": "a.md", "quote": "q", "source": "[[A]]"},
]


def test_quiz_questions_are_well_formed(monkeypatch):
    monkeypatch.setattr(learning, "query_claims", lambda *a, **k: {"claims": FACTS})
    qs = quiz.make_quiz(n=10, seed=1)
    assert qs
    for q in qs:
        assert q["answer"] in q["options"] and len(set(q["options"])) == 4
        assert "_____" in q["question"]
        assert q["question"].replace("_____", q["answer"], 1) == q["fact"]      # blank is exactly the answer
        assert "U_____" not in q["question"] and "_____ing" not in q["question"]  # never inside a word


def test_blank_never_cuts_a_word():
    assert quiz._blank("Underfitting and fitting.", "fitting") == "Underfitting and _____."
