"""Regression gate (pytest -m eval): the current verifier, re-run on the labelled sentences, must stay precise.

Needs the local NLI model; scores are cached, so re-runs take seconds. Excluded from the default test run.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

STRICT_FLOOR, LENIENT_FLOOR = 90.5, 99.0   # 18 Oct: title-context retry on (gold 91.1% / 99.5%), user-approved trade: +30 correct, +5 imprecise, 0 wrong


@pytest.mark.eval
def test_precision_does_not_regress():
    import gate
    r = gate.run()
    for name in ("gold", "baseline"):
        assert r[name]["precision_strict"] >= STRICT_FLOOR, (name, r[name])
        assert r[name]["precision_lenient"] >= LENIENT_FLOOR, (name, r[name])
    assert r["baseline"]["wrong_accepted"] == 0, r["baseline"]
