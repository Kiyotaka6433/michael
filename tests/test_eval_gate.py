"""Regression gate (pytest -m eval): the current verifier, re-run on the labelled sentences, must stay precise.

Needs the local NLI model; scores are cached, so re-runs take seconds. Excluded from the default test run.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

STRICT_FLOOR, LENIENT_FLOOR = 91.5, 99.0   # just under the 17 Oct baseline (91.8% / 99.5% gold)


@pytest.mark.eval
def test_precision_does_not_regress():
    import gate
    r = gate.run()
    for name in ("gold", "baseline"):
        assert r[name]["precision_strict"] >= STRICT_FLOOR, (name, r[name])
        assert r[name]["precision_lenient"] >= LENIENT_FLOOR, (name, r[name])
    assert r["baseline"]["wrong_accepted"] == 0, r["baseline"]
