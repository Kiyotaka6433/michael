"""Independent verifier: an NLI model (never the writing LLM) judges whether a quote entails a sentence.

Speed on CPU: the model is forced to float32 (newer transformers load the stored float16 weights, which run
~7x slower on CPUs), pairs are length-sorted to minimise padding, all sentences of a round are scored in one
batch, and only short quote windows (1-3 sentences) are scored, never whole passages.
"""
import json
import os
import re

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
        out = [tuple(cached[k]) for k in keys]
        record = os.getenv("MICHAEL_RECORD_NLI")          # calibration data for the verifier cascade
        if record:
            with open(record, "a", encoding="utf8") as f:
                for (p, h), (ent, con) in zip(pairs, out):
                    f.write(json.dumps({"p": p, "h": h, "ent": ent, "con": con}, ensure_ascii=False) + "\n")
        return out

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


class CascadeNLI(NLI):
    """Two-stage verifier: a small NLI model (~6x faster) screens every uncached pair; only pairs it does not
    clearly reject go to the large model. The small model never ACCEPTS anything - a pair it rejects keeps its
    (low) small-model score, everything that could pass is judged by the large model, so precision is the large
    model's. `cut` is calibrated so that (almost) no pair the large model would accept is screened out."""

    def __init__(self, cut: float, small: str = "tasksource/deberta-small-long-nli", model_name: str | None = None):
        super().__init__(model_name)
        self.cut, self.small = cut, NLI(small)
        self.stats = {"pairs": 0, "large": 0}

    def scores(self, pairs: list[tuple[str, str]]) -> list[tuple[float, float]]:
        from .. import db
        keys = [sha(f"{self.model_name}|{p}|{h}") for p, h in pairs]
        try:
            cached = db.cache_get("nli", list(set(keys)))
        except Exception:
            cached = {}
        todo = [i for i, k in enumerate(keys) if k not in cached]
        out = [tuple(cached[k]) if k in cached else None for k in keys]
        if todo:
            screen = self.small.scores([pairs[i] for i in todo])          # cached under the small model's name
            keep = [i for i, (ent, _) in zip(todo, screen) if ent >= self.cut]
            for i, s in zip(todo, screen):
                out[i] = tuple(s)
            if keep:
                big = NLI.scores(self, [pairs[i] for i in keep])         # large model, with its own cache
                for i, s in zip(keep, big):
                    out[i] = tuple(s)
            self.stats["pairs"] += len(todo)
            self.stats["large"] += len(keep)
        return out


def make_verifier() -> NLI:
    return CascadeNLI(settings.cascade_cut) if settings.cascade_cut > 0 else NLI()


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


PRONOUN = re.compile(r"^(It|This (?:algorithm|method|data structure|structure|technique|approach|procedure|theorem|"
                     r"result|function|model|test)|The (?:algorithm|method|data structure|technique|approach|"
                     r"procedure))\b")
SITE = re.compile(r"\s*\((?:cp-algorithms|scikit-learn|d2l\.ai|[^()]*(?:Algorithms|Guide|Brilliant|CS231n|Distill|Lil'Log|"
                  r"blog|Pages|stanford\.edu)[^()]*)\)\s*$|\s+-\s+key points$", re.I)


def subject_of(title: str) -> str:
    """'Dijkstra Algorithm (cp-algorithms)' -> 'Dijkstra Algorithm'."""
    return SITE.sub("", title or "").strip()


def decontextualise(sentence: str, subject: str) -> str | None:
    """'It runs in O(n log n).' + 'Merge sort' -> 'Merge sort runs in O(n log n).' The verifier can't check a
    sentence whose subject is a pronoun, so many true sentences were removed. Rule-based (no LLM): only a sentence
    that *starts* with it / this algorithm / the method..., and only with the cited source's own title."""
    if not subject or not PRONOUN.match(sentence) or subject.lower() in sentence.lower():
        return None
    return PRONOUN.sub(subject, sentence, count=1)


VERB = (r"(?:is|are|was|were|can|could|has|have|had|uses|use|runs|run|merges|combines|returns|computes|finds|"
        r"supports|requires|takes|works|maintains|stores|selects|builds|allows|provides|achieves|introduces|"
        r"proposes|reduces|improves|detects|solves|guarantees|produces|gives|holds|states|defines|describes)")
JOIN = re.compile(rf",?\s+and\s+(?=(?:it\s+|its\s+|they\s+|their\s+)?{VERB}\b)|,\s+which\s+(?={VERB}\b)|;\s+")


def split_claim(sentence: str) -> list[str] | None:
    """'Kruskal's algorithm was described by Kruskal in 1956 and combines edges in sorted order.' ->
    ['Kruskal's algorithm was described by Kruskal in 1956.', 'Kruskal's algorithm combines edges in sorted order.']
    No single quote proves a two-fact sentence, so true compound sentences were removed. Each part gets the
    sentence's subject (the words before its first verb); None if the sentence isn't a clean compound."""
    body = sentence.rstrip(" .")
    m = re.search(rf"\b{VERB}\b", body)
    if not m:
        return None
    subject = body[:m.start()].strip().rstrip(",")
    if not (1 <= len(subject.split()) <= 8):
        return None
    pieces = JOIN.split(body)
    if len(pieces) < 2:
        return None
    parts = [pieces[0].strip()]
    for p in pieces[1:]:
        p = re.sub(r"^(it|they)\s+", "", p.strip(), flags=re.I)
        p = re.sub(r"^(its|their)\s+", f"{subject}'s ", p, flags=re.I) if not p.lower().startswith(subject.lower()) else p
        parts.append(p if p.lower().startswith(subject.lower()) or p.startswith(subject + "'s") else f"{subject} {p}")
    parts = [p.rstrip(" ,.") + "." for p in parts]
    return parts if all(len(p.split()) >= 3 for p in parts) else None


def _prove_parts(claims, found, evidence, nli, recite):
    """Still-failing compound sentences: split, prove every part (in the cited passages, and anywhere in the
    evidence when re-citation is on). All parts proven -> the sentence is SUPPORTED with the parts' quotes."""
    jobs = []
    for i, (cl, f) in enumerate(zip(claims, found)):
        if f is not None and f[1][0] >= settings.support_threshold:
            continue
        parts = split_claim(cl.sentence)
        if not parts:
            continue
        cited = [evidence[l] for l in cl.citations if l in evidence]
        pool = list(evidence.values()) if recite else cited
        for p in parts:
            part = Claim(index=cl.index, sentence=p, citations=list(cl.citations))
            wins = _windows(part, cited) + [w for w in _windows(part, [c for c in pool if c not in cited], top=2,
                                                                context=False)]
            jobs.append((i, part, wins))
    if not jobs:
        return {}
    results = _score_groups([w for _, _, w in jobs], [p for _, p, _ in jobs], nli)
    by_claim = {}
    for (i, _, _), r in zip(jobs, results):
        by_claim.setdefault(i, []).append(r)
    proven = {}
    for i, rs in by_claim.items():
        if all(r and r[1][0] >= settings.support_threshold for r in rs):
            found[i] = (rs[0][0], (min(r[1][0] for r in rs), max(r[1][1] for r in rs)))
            proven[i] = [r[0] for r in rs]
    return proven


TITLED_MIN_OVERLAP = 70    # token_set_ratio: correct cases 82-85, the false Sieve citation 58


def _titled_retry(claims, found, evidence, nli, recite):
    """Quotes often refer to their subject by pronoun ("In both contexts, it refers to simplifying a complicated
    problem..."), so the NLI model can't tell that "it" is dynamic programming and scores a near-verbatim sentence
    at ~0. Still-failing sentences are judged again with the source title and section heading in front of each
    quote window: "Dynamic programming - Overview: In both contexts, it refers to ...". The shown quote is unchanged."""
    jobs = []
    for i, (cl, f) in enumerate(zip(claims, found)):
        if f is not None and f[1][0] >= settings.support_threshold:
            continue
        cited = [evidence[l] for l in cl.citations if l in evidence]
        pool = cited + ([c for c in evidence.values() if c not in cited] if recite else [])
        wins = []
        for c in pool[:12]:
            subject = subject_of(c.title)
            head = f"{subject} - {c.heading}" if c.heading and c.heading.lower() != subject.lower() else subject
            for s, e in lexical_candidates(cl.sentence, c.text, top=2 if c in cited else 1):
                # the title only resolves who "it" is: the quote itself must already carry the sentence's wording.
                # Without this, "Sieve of Eratosthenes: If n is composite, it has a divisor <= sqrt(n)" was
                # accepted (0.99) for a sentence about listing the integers 2..n - true, but not what the quote says
                if fuzz.token_set_ratio(cl.sentence, c.text[s:e]) < TITLED_MIN_OVERLAP:
                    continue
                wins.append((c, s, e, f"{head}: {c.text[s:e]}"))
        jobs += [(i, w) for w in wins]
    if not jobs:
        return set()
    scores = nli.scores([(w[3], claims[i].sentence) for i, w in jobs])
    best = {}
    for (i, (c, s, e, _)), (ent, con) in zip(jobs, scores):
        if ent >= settings.support_threshold and ent > best.get(i, (None, (0, 0)))[1][0]:
            best[i] = ((c, s, e, s, e), (ent, con))
    for i, f in best.items():
        found[i] = f
        claims[i].citations = [f[0][0].label]
    return set(best)


def _two_quote_retry(claims, found, evidence, nli) -> dict:
    """A sentence that joins two facts from neighbouring source sentences ("Dijkstra runs n iterations, selecting
    the unmarked vertex with the smallest d[v]") has no single quote that proves it. Still-failing sentences are
    judged once more against their two closest windows of the cited passage, joined in source order. Returns
    {claim index: (chunk, (s1, e1), (s2, e2))} for the ones that pass; their quote shows both windows."""
    jobs = []
    for i, (cl, f) in enumerate(zip(claims, found)):
        if f is not None and f[1][0] >= settings.support_threshold:
            continue
        for c in [evidence[l] for l in cl.citations if l in evidence][:2]:
            cands = lexical_candidates(cl.sentence, c.text, top=8)
            if not cands:
                continue
            best = cands[0]                                           # closest window, then the closest one
            other = next((w for w in cands[1:] if w[1] <= best[0] or w[0] >= best[1]), None)   # NOT overlapping it
            if other:
                (s1, e1), (s2, e2) = sorted([best, other])            # in source order
                jobs.append((i, c, (s1, e1), (s2, e2), f"{c.text[s1:e1]} … {c.text[s2:e2]}"))
    if not jobs:
        return {}
    passed = {}
    for (i, c, w1, w2, premise), (ent, con) in zip(jobs, nli.scores([(j[4], claims[j[0]].sentence) for j in jobs])):
        # joined windows give context the way a paragraph does, so they need the paragraph's bar (0.90), not 0.70
        if ent >= settings.context_threshold and i not in passed:
            found[i] = ((c, w1[0], w2[1], w1[0], w2[1]), (ent, con))
            claims[i].citations = [c.label]
            passed[i] = (c, w1, w2)
    return passed


def verify_claims(claims: list[Claim], evidence: dict[str, Chunk], nli: NLI, recite: bool = True) -> list[Verdict]:
    """Check every claim against quote windows of the passages it cites.
    If those fail but another passage proves the sentence, the citation is corrected to that passage
    (small LLMs often cite the neighbour of the right passage)."""
    groups = [_windows(cl, [evidence[l] for l in cl.citations if l in evidence]) for cl in claims]
    if settings.early_exit:
        # most true sentences pass on their closest quote window: score only that one first (one NLI pass for all
        # claims), and run the full window set only for those that don't pass - same verdicts, far fewer pairs
        first = _score_groups([g[:1] for g in groups], claims, nli)
        rest = [i for i, f in enumerate(first) if f is None or f[1][0] < settings.support_threshold]
        found = list(first)
        if rest:
            for i, f in zip(rest, _score_groups([groups[i] for i in rest], [claims[i] for i in rest], nli)):
                found[i] = f
    else:
        found = _score_groups(groups, claims, nli)
    if settings.decontextualise:
        # a failing sentence that starts with "It ..." is tried again with the cited source's subject in its place
        alts = []
        for i, (cl, f) in enumerate(zip(claims, found)):
            if f is not None and f[1][0] >= settings.support_threshold:
                continue
            cited = [evidence[l] for l in cl.citations if l in evidence]
            new = decontextualise(cl.sentence, subject_of(cited[0].title)) if cited else None
            if new:
                alts.append((i, Claim(index=cl.index, sentence=new, citations=list(cl.citations)), cited))
        if alts:
            alt_found = _score_groups([_windows(c, cited) for _, c, cited in alts], [c for _, c, _ in alts], nli)
            for (i, c, _), f in zip(alts, alt_found):
                if f and f[1][0] >= settings.support_threshold:
                    found[i] = f
                    claims[i].sentence = c.sentence          # the note shows the self-contained sentence
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
    titled = _titled_retry(claims, found, evidence, nli, recite) if settings.titled_premise else set()
    two = _two_quote_retry(claims, found, evidence, nli) if settings.two_quotes else {}
    proven = _prove_parts(claims, found, evidence, nli, recite) if settings.decompose else {}
    verdicts = []
    for i, (cl, f) in enumerate(zip(claims, found)):
        if f is None:
            verdicts.append(Verdict(claim_index=cl.index, label="UNSUPPORTED"))
            continue
        (chunk, s, e, js, je), (ent, con) = f
        in_context = (js, je) != (s, e)
        label, math = label_for(ent), ""
        near = False
        if (settings.near_verbatim and label == "PARTIAL" and ent >= settings.near_verbatim_min
                and fuzz.token_set_ratio(cl.sentence, chunk.text[s:e]) >= settings.near_verbatim_overlap):
            # the sentence restates its quote almost word for word; the NLI model's 0.5-0.7 is wording noise, not
            # missing content (shown in the footnote as "near-verbatim")
            label, near = "SUPPORTED", True
        if settings.math_check and label != "UNSUPPORTED":
            # the NLI model reads formulas and numbers as text: check them against the evidence paragraph
            from .ophaniel import check
            ps, pe = paragraph_of(chunk.text, s, e)
            text = chunk.text[min(ps, js):max(pe, je)]
            if i in proven:                          # proven in parts: the numbers may sit in any part's passage
                text = "\n\n".join(c.text[slice(*paragraph_of(c.text, a, b))] for c, a, b, _, _ in proven[i])
            mv = check(cl.sentence, text)
            math = mv.status
            if mv.status == "mismatch":
                label = "UNSUPPORTED"
            elif label == "PARTIAL" and mv.complete and settings.math_upgrade:
                # the text is partly entailed and every formula is proven equivalent to the evidence's: the gap
                # was the notation (e.g. d_k^{-1/2} vs 1/sqrt(d_k)), not the content
                label, math = "SUPPORTED", "proven"
        if in_context and je - js <= 700:            # judged in context: show the reader that whole paragraph
            s, e = js, je
        quote = chunk.text[s:e]
        if i in two:                                 # the two windows only, not the text between them
            c2, (a1, b1), (a2, b2) = two[i]
            quote = f"{c2.text[a1:b1]} … {c2.text[a2:b2]}"
        if i in proven:                              # every part's own quote, in order
            quote = " … ".join(c.text[a:b] for c, a, b, _, _ in proven[i])
        verdicts.append(Verdict(claim_index=cl.index, label=label, chunk_id=chunk.id,
                                evidence_label=chunk.label, quote=quote, quote_start=s, quote_end=e,
                                entailment=ent, contradiction=con, in_context=in_context, math=math,
                                parts=len(proven.get(i, [])), titled=i in titled and i not in proven,
                                near_verbatim=near))
    if settings.conflict_check:
        flag_conflicts(claims, verdicts, evidence, nli)
    return verdicts


def flag_conflicts(claims: list[Claim], verdicts: list[Verdict], evidence: dict[str, Chunk], nli: NLI,
                   per_claim: int = 2, threshold: float = 0.90):
    """For each verified sentence, check the closest windows of the OTHER sources (different article) in one NLI
    batch. A window that clearly contradicts it (contradiction >= threshold, entailment < 0.10) is attached to the
    verdict, so the note can say that the sources disagree instead of silently picking one."""
    by_id = {c.id: c for c in evidence.values()}
    pairs, owners = [], []
    for cl, v in zip(claims, verdicts):
        if v.label != "SUPPORTED" or v.chunk_id not in by_id:
            continue
        own = by_id[v.chunk_id].source_id
        cands = []
        for c in evidence.values():
            if c.source_id == own:
                continue
            for s, e in lexical_candidates(cl.sentence, c.text, top=1):
                cands.append((fuzz.token_set_ratio(cl.sentence, c.text[s:e]), c, s, e))
        for _, c, s, e in sorted(cands, key=lambda x: -x[0])[:per_claim]:
            pairs.append((c.text[s:e], cl.sentence))
            owners.append((v, c, s, e))
    if not pairs:
        return
    for (v, c, s, e), (ent, con) in zip(owners, nli.scores(pairs)):
        if con >= threshold and ent < 0.10 and con > v.conflict_score:
            v.conflict_label, v.conflict_quote, v.conflict_score = c.label, c.text[s:e], con


def verify_claim(claim: Claim, evidence: dict[str, Chunk], nli: NLI, recite: bool = True) -> Verdict:
    return verify_claims([claim], evidence, nli, recite)[0]
