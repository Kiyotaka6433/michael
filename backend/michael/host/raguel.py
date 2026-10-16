"""Independent verifier: an NLI model (never the writing LLM) judges whether a quote entails a sentence.

Speed on CPU: the model is forced to float32 (newer transformers load the stored float16 weights, which run
~7x slower on CPUs), pairs are length-sorted to minimise padding, all sentences of a round are scored in one
batch, and only short quote windows (1-3 sentences) are scored, never whole passages.
"""
from rapidfuzz import fuzz

from ..config import settings
from ..models import Chunk, Claim, Verdict
from .uriel import lexical_candidates


class NLI:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.nli_model
        self._tok = self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self._tok = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name, dtype=torch.float32).eval()
            labels = {v.lower(): k for k, v in self._model.config.id2label.items()}
            self._ent, self._con = labels["entailment"], labels["contradiction"]

    def scores(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
        """(entailment, contradiction) probability for each (premise, hypothesis) pair."""
        import torch
        self._load()
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][0]) + len(pairs[i][1]))
        out: list = [None] * len(pairs)
        for b in range(0, len(order), 16):
            idx = order[b:b + 16]
            enc = self._tok([pairs[i][0] for i in idx], [pairs[i][1] for i in idx], truncation="only_first",
                            max_length=512, padding=True, return_tensors="pt")
            with torch.inference_mode():
                probs = self._model(**enc).logits.softmax(-1)
            for i, p in zip(idx, probs):
                out[i] = (float(p[self._ent]), float(p[self._con]))
        return out


def label_for(entailment: float) -> str:
    if entailment >= settings.support_threshold:
        return "SUPPORTED"
    if entailment >= settings.partial_threshold:
        return "PARTIAL"
    return "UNSUPPORTED"


def _windows(claim: Claim, chunks: list[Chunk], top: int = 3):
    return [(c, s, e) for c in chunks for s, e in lexical_candidates(claim.sentence, c.text, top=top)]


def _pick(cands, scores):
    """Tightest quote that proves the sentence; otherwise the strongest partial evidence."""
    passing = [i for i in range(len(cands)) if scores[i][0] >= settings.support_threshold]
    if passing:
        best = min(passing, key=lambda i: (cands[i][2] - cands[i][1], -scores[i][0]))
    else:
        best = max(range(len(cands)), key=lambda i: (scores[i][0], -(cands[i][2] - cands[i][1])))
    return cands[best], scores[best]


def _score_groups(groups: list[list], claims: list[Claim], nli: NLI) -> list:
    """Score every (window, claim) pair of every claim in one batch; returns the best pick per claim (or None)."""
    pairs = [(c.text[s:e], claim.sentence) for g, claim in zip(groups, claims) for c, s, e in g]
    flat = nli.scores(pairs) if pairs else []
    out, k = [], 0
    for g in groups:
        out.append(_pick(g, flat[k:k + len(g)]) if g else None)
        k += len(g)
    return out


def verify_claims(claims: list[Claim], evidence: dict[str, Chunk], nli: NLI, recite: bool = True) -> list[Verdict]:
    """Check every claim against quote windows of the passages it cites.
    If those fail but another passage proves the sentence, the citation is corrected to that passage
    (small LLMs often cite the neighbour of the right passage)."""
    groups = [_windows(cl, [evidence[l] for l in cl.citations if l in evidence]) for cl in claims]
    found = _score_groups(groups, claims, nli)
    if recite:
        retry = [i for i, f in enumerate(found) if f is None or f[1][0] < settings.support_threshold]
        alt_groups = []
        for i in retry:
            cl = claims[i]
            others = [c for l, c in evidence.items() if l not in cl.citations]
            pool = _windows(cl, others, top=2)
            pool.sort(key=lambda w: fuzz.token_set_ratio(cl.sentence, w[0].text[w[1]:w[2]]), reverse=True)
            alt_groups.append(pool[:4])
        for i, alt in zip(retry, _score_groups(alt_groups, [claims[i] for i in retry], nli)):
            if alt and alt[1][0] >= settings.support_threshold:
                found[i] = alt
                claims[i].citations = [alt[0][0].label]
    verdicts = []
    for cl, f in zip(claims, found):
        if f is None:
            verdicts.append(Verdict(claim_index=cl.index, label="UNSUPPORTED"))
            continue
        (chunk, s, e), (ent, con) = f
        verdicts.append(Verdict(claim_index=cl.index, label=label_for(ent), chunk_id=chunk.id,
                                evidence_label=chunk.label, quote=chunk.text[s:e], quote_start=s, quote_end=e,
                                entailment=ent, contradiction=con))
    return verdicts


def verify_claim(claim: Claim, evidence: dict[str, Chunk], nli: NLI, recite: bool = True) -> Verdict:
    return verify_claims([claim], evidence, nli, recite)[0]
