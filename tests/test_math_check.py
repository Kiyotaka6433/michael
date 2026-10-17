"""Maths-aware verification (ophaniel): formulas, big-O and numbers are checked against the evidence."""
import pytest

from michael.host import ophaniel as O

CASES = [
    (r"Each dot product is divided by $\sqrt{d_k}$.", r"divide each by $\sqrt{d_k}$, and apply a softmax", "match"),
    (r"The scaling factor is $\frac{1}{d_k}$.", r"except for the scaling factor of $\frac{1}{\sqrt{d_k}}$.", "mismatch"),
    (r"The sieve runs in $O(n \log \log n)$ time.", r"The algorithm runs in $O(n \log \log n)$ operations.", "match"),
    (r"The sieve runs in $O(n \log n)$ time.", r"The algorithm runs in $O(n \log \log n)$ operations.", "mismatch"),
    (r"It is $O(3 n)$.", r"It is $O(n)$.", "match"),                                   # constants don't change O
    (r"$x^2 + 2x + 1 = (x+1)^2$ holds.", r"Note that $(x+1)^2 = x^2+2x+1$.", "match"),  # sides swapped
    (r"$x^2 + 3x + 1 = (x+1)^2$ holds.", r"Note that $(x+1)^2 = x^2+2x+1$.", "mismatch"),
    ("The model achieves 28.4 BLEU.", "Our model achieves 28.4 BLEU on the WMT 2014 task", "match"),
    ("The model achieves 29.4 BLEU.", "Our model achieves 28.4 BLEU on the WMT 2014 task", "mismatch"),
    (r"Lookups take $O(1)$ time.", "Arrays allow constant-time lookups.", "unchecked"),     # nothing to compare
]


@pytest.mark.parametrize("claim,evidence,expected", CASES)
def test_math_verdicts(claim, evidence, expected):
    assert O.check(claim, evidence).status == expected


def test_unrelated_formulas_are_never_a_mismatch():
    # different symbols: not comparable, so the NLI verdict stands
    assert O.check(r"Here $a + b = c$.", r"Elsewhere $x y = z$.").status == "unchecked"


def test_numbers_written_as_words_or_with_trailing_zeros_match():
    assert O.check("BERT set records on 11 tasks.", "It obtains new state-of-the-art results on eleven tasks").status == "match"
    assert O.check("The rate was 1.50 percent.", "a rate of 1.5 percent").status == "match"


def test_a_formula_quoted_verbatim_matches_and_constants_are_not_cross_compared():
    ev = r"Consider $7^{222}{\pmod {10}}$ . The integers 7 and 10 are coprime, and $\varphi (10)=4$ ."
    assert O.check(r"The integers 7 and 10 are coprime, and $\varphi (10)=4$ .", ev).status == "match"
    assert O.check(r"We have $2^{10} = 1024$.", r"Recall $2^{10} = 1000$.").status == "mismatch"
