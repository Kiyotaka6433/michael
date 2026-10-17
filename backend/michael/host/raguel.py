"""Independent verifier: an NLI model (never the writing LLM) judges whether a quote entails a sentence.

Speed on CPU: the model is forced to float32 (newer transformers load the stored float16 weights, which run
~7x slower on CPUs), pairs are length-sorted to minimise padding, all sentences of a round are scored in one
batch, and only short quote windows (1-3 sentences) are scored, never whole passages.
"""
from rapidfuzz import fuzz

from ..config import settings
from ..models import Chunk, Claim, Verdict, sha
from .uriel import lexical_candidates, paragraph_of


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
        """(entailment, contradiction) probability for each (premise, hypothesis) pair, with a persistent cache:
        re-verifying a note, or the same quote for the same sentence, costs nothing."""
        from .. import db
        keys = [sha(f"{self.model_name}|{p}|{h}") for p, h in pairs]
        try:
            cached = db.cache_get("nli", list(set(keys)))
        except Exception:
            cached = {}
        todo = [i for i, k in enumerate(keys) if k not in cached]
        fresh = self._scores([pairs[i] for i in todo]) if todo else []
        if fresh:
            new = {keys[i]: list(v) for i, v in zip(todo, fresh)}
            try:
                db.cache_put("nli", new)
            except Exception:
                pass
            cached.update(new)
        return [tuple(cached[k]) for k in keys]

    def _scores(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
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


def _windows(claim: Claim, chunks: list[Chunk], top: int = 3, context: bool = True):
    """Candidates (chunk, quote_start, quote_end, judged_start, judged_end). Each quote window is judged alone;
    the best one is also judged inside its paragraph, because a sentence like "our model achieves 41.8 BLEU"
    only supports "the Transformer achieves 41.8 BLEU" when the NLI model can see what "our model" is."""
    out = []
    for c in chunks:
        wins = lexical_candidates(claim.sentence, c.text, top=top)
        out += [(c, s, e, s, e) for s, e in wins]
        if context and wins:
            s, e = wins[0]
            ps, pe = paragraph_of(c.text, s, e)
            if (ps, pe) != (s, e) and ps <= s and e <= pe:
                out.append((c, s, e, ps, pe))
    return out


def _pick(cands, scores):
    """Tightest quote that proves the sentence; otherwise the strongest partial evidence."""
    passing = [i for i in range(len(cands)) if scores[i][0] >= settings.support_threshold]
    if passing:
        best = min(passing, key=lambda i: (cands[i][4] - cands[i][3], -scores[i][0]))
    else:
        best = max(range(len(cands)), key=lambda i: (scores[i][0], -(cands[i][4] - cands[i][3])))
    return cands[best], scores[best]


def _score_groups(groups: list[list], claims: list[Claim], nli: NLI) -> list:
    """Score every (window, claim) pair of every claim in one batch; returns the best pick per claim (or None)."""
    pairs = [(c.text[js:je], claim.sentence) for g, claim in zip(groups, claims) for c, _, _, js, je in g]
    flat = nli.scores(pairs) if pairs else []
    # a whole paragraph lets loosely-worded sentences through, so passing *only in context* needs a much higher
    # score; below it the sentence can at most be PARTIAL
    cands = [w for g in groups for w in g]
    flat = [(min(ent, settings.support_threshold - 0.01), con)
            if (w[3], w[4]) != (w[1], w[2]) and ent < settings.context_threshold else (ent, con)
            for w, (ent, con) in zip(cands, flat)]
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
            pool = _windows(cl, others, top=3, context=False)
            pool.sort(key=lambda w: fuzz.token_set_ratio(cl.sentence, w[0].text[w[1]:w[2]]), reverse=True)
            pool = pool[:5]
            if pool:                                  # the best one also in its paragraph
                c, s, e = pool[0][:3]
                ps, pe = paragraph_of(c.text, s, e)
                if (ps, pe) != (s, e):
                    pool.append((c, s, e, ps, pe))
            alt_groups.append(pool)
        for i, alt in zip(retry, _score_groups(alt_groups, [claims[i] for i in retry], nli)):
            if alt and alt[1][0] >= settings.support_threshold:
                found[i] = alt
                claims[i].citations = [alt[0][0].label]
    verdicts = []
    for cl, f in zip(claims, found):
        if f is None:
            verdicts.append(Verdict(claim_index=cl.index, label="UNSUPPORTED"))
            continue
        (chunk, s, e, js, je), (ent, con) = f
        in_context = (js, je) != (s, e)
        label, math = label_for(ent), ""
        if settings.math_check and label != "UNSUPPORTED":
            # the NLI model reads formulas and numbers as text: check them against the evidence paragraph
            from .ophaniel import check
            ps, pe = paragraph_of(chunk.text, s, e)
            mv = check(cl.sentence, chunk.text[min(ps, js):max(pe, je)])
            math = mv.status
            if mv.status == "mismatch":
                label = "UNSUPPORTED"
        if in_context and je - js <= 700:            # judged in context: show the reader that whole paragraph
            s, e = js, je
        verdicts.append(Verdict(claim_index=cl.index, label=label, chunk_id=chunk.id,
                                evidence_label=chunk.label, quote=chunk.text[s:e], quote_start=s, quote_end=e,
                                entailment=ent, contradiction=con, in_context=in_context, math=math))
    return verdicts


def verify_claim(claim: Claim, evidence: dict[str, Chunk], nli: NLI, recite: bool = True) -> Verdict:
    return verify_claims([claim], evidence, nli, recite)[0]
