"""Draft an answer in which every sentence cites evidence labels such as p1, p3."""
import json
import re

from ..config import settings
from .. import llm
from ..llm import chat_json
from ..models import Chunk, Claim
from .scrolls import split_sentences

SYSTEM = """You write short, factual research notes using ONLY the numbered evidence passages provided.
Rules:
- Write 4 to 10 sentences. Each sentence states ONE fact taken from ONE passage, and cites that passage.
- Stay close to the passage wording. Never add outside knowledge, never guess.
- Do not join two facts with "while", "whereas" or "and"; write two sentences instead.
- For an algorithm or procedure, write one sentence per step ("first ..., then ..., finally ..." is three sentences).
- Cover every part of the question that the passages answer.

Example
Question: How do cats and dogs differ in sleep?
[p1] Cats sleep 12 to 16 hours a day. [p2] Dogs sleep about 12 hours a day. Puppies sleep up to 20 hours.
Answer: {"sentences": [
 {"text": "Cats sleep 12 to 16 hours a day.", "citations": ["p1"]},
 {"text": "Dogs sleep about 12 hours a day.", "citations": ["p2"]},
 {"text": "Puppies can sleep up to 20 hours a day.", "citations": ["p2"]}]}

Return JSON: {"sentences": [{"text": "...", "citations": ["pN"]}]}"""

SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "minItems": 3, "maxItems": 8, "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "citations": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
        "required": ["text", "citations"]}}},
    "required": ["sentences"],
}


def evidence_block(evidence: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.label}] ({c.title}{' - ' + c.heading if c.heading else ''})\n{c.text}" for c in evidence)


# sentences about the prompt instead of the topic ("... is not discussed in the provided passages")
META = re.compile(r"\b(provided|given) (passages?|evidence|text|sources?)\b|\bthe passages?\b"
                  r"|\bnot (explicitly )?(discussed|mentioned|covered|described) in the\b", re.I)
CONTRAST = re.compile(r",?\s+(?:while|whereas)\s+", re.I)


def split_compound(text: str) -> list[str]:
    """'A is X, while B is Y.' -> ['A is X.', 'B is Y.']: each half can then be proven by its own quote.
    Small models join facts from two passages this way even when told not to."""
    parts = CONTRAST.split(text.strip())
    if len(parts) != 2 or any(len(p.split()) < 3 for p in parts):
        return [text]
    first = parts[1].split()[0].lower()
    if first.endswith("ing") or first in ("still", "also", "being", "maintaining", "keeping"):
        return [text]        # "..., while still having lower complexity": a participle, not a second fact
    a, b = (p.strip().rstrip(".") for p in parts)
    return [a[0].upper() + a[1:] + ".", b[0].upper() + b[1:] + "."]


def parse_sentences(data: dict, valid_labels: set) -> list[Claim]:
    claims, seen = [], set()
    for item in data.get("sentences", []):
        if isinstance(item, str):
            text, cites = item, []
        else:
            text, cites = str(item.get("text", "")).strip(), item.get("citations", []) or []
        cites = [c.strip("[] ") for c in cites if isinstance(c, str)]
        cites = [c for c in dict.fromkeys(cites) if c in valid_labels]
        # one claim per sentence: a two-sentence item could pass on the strength of only one of them
        parts = [p for sent in (split_sentences(text) if text else []) for p in split_compound(sent)]
        for part in parts:
            if META.search(part):         # about the prompt, not the topic
                continue
            key = " ".join(part.lower().split())
            if key not in seen:               # small models sometimes repeat sentences
                seen.add(key)
                claims.append(Claim(index=len(claims), sentence=part, citations=list(cites)))
    return claims


def prefill(max_sentences: int = 8):
    """Read the writer's fixed instructions into Ollama's prompt cache NOW, in the background, while the run is still
    searching and reranking: the draft then only reads the question and the evidence (speed)."""
    if settings.prefill and not settings.compact_writer:
        llm.prefill(_prompt(max_sentences)[0], settings.writer_model or settings.llm_model)


def _prompt(max_sentences: int) -> tuple[str, dict]:
    system, schema = SYSTEM, SCHEMA
    if settings.writer_style == "extractive":
        # recall experiment: drafts that summarise or reorder the source are what the verifier can't prove;
        # ask for sentences that each restate ONE passage sentence, shortened, in its own words and order
        system = system.replace("- Stay close to the passage wording.",
                                "- Each sentence restates ONE sentence of a passage: shorten it, but keep its words and "
                                "word order, and name the subject instead of 'it' or 'this algorithm'.\n"
                                "- Stay close to the passage wording.", 1)
    if max_sentences != 8:
        system = system.replace("Write 4 to 10 sentences.", f"Write 6 to {max_sentences} sentences.", 1)
        schema = {**SCHEMA, "properties": {"sentences": {**SCHEMA["properties"]["sentences"], "maxItems": max_sentences}}}
    return system, schema


def write(question: str, evidence: list[Chunk], max_sentences: int = 8) -> list[Claim]:
    """max_sentences > 8 for overviews built from many articles (one or two facts per passage)."""
    system, schema = _prompt(max_sentences)
    model = settings.writer_model or settings.llm_model
    user = f"Question: {question}\n\nEvidence passages:\n\n{evidence_block(evidence)}"
    passages = {(c.label, c.text) for c in evidence}
    if settings.compact_writer:
        # "p3 | sentence" lines: about a third fewer tokens to generate than the JSON objects, and no constrained
        # decoding. Falls back to JSON if the answer can't be read.
        text = llm.chat_text(compact(system), user, model=model)
        items = parse_lines(text)["sentences"][:max_sentences]          # the JSON schema's maxItems
        claims = parse_sentences({"sentences": items}, {c.label for c in evidence})
        if len(claims) >= 2:
            llm.remember_conversation(passages, model, [{"role": "system", "content": compact(system)},
                                                        {"role": "user", "content": user}], text)
            return claims
    data = chat_json(system, user, schema=schema, model=model)
    llm.remember_conversation(passages, model, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                              llm.LAST_REPLY["text"] or json.dumps(data, ensure_ascii=False))   # exact text: cache hit
    return parse_sentences(data, {c.label for c in evidence})


LINE = re.compile(r"^\s*(?:[-*]|\d+[.)])?\s*\[?((?:p\d+\]?\s*,?\s*\[?)+)\]?\s*[|:]?\s*(.+?)\s*$")


def compact(system: str) -> str:
    """The writer's instructions with the JSON example and format rewritten as one "pN | sentence" line each."""
    return system.split("Example", 1)[0] + """Example
Question: How do cats and dogs differ in sleep?
[p1] Cats sleep 12 to 16 hours a day. [p2] Dogs sleep about 12 hours a day. Puppies sleep up to 20 hours.
Answer:
p1 | Cats sleep 12 to 16 hours a day.
p2 | Dogs sleep about 12 hours a day.
p2 | Puppies can sleep up to 20 hours a day.

Answer with one line per sentence: the passage label(s), a | and the sentence. Nothing else."""


def parse_lines(text: str) -> dict:
    """'p1, p3 | sentence' lines -> the writer's JSON shape."""
    out = []
    for line in text.splitlines():
        if m := LINE.match(line):
            out.append({"text": m.group(2), "citations": re.findall(r"p\d+", m.group(1))})
    return {"sentences": out}
