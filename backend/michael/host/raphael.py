"""Rewrite unsupported sentences so they say only what the evidence supports, or drop them.
All failed sentences of a round go to the LLM in ONE call, with only the passages they relate to."""
from ..llm import chat_json
from ..models import Chunk, Claim
from .metatron import evidence_block

SYSTEM = """Some sentences in a research note are not supported by the evidence passages.
For each sentence, rewrite it so it states ONLY what the passages explicitly say (short, one fact, close to
the passage wording) and cite the passage label it comes from. If the passages cannot support any version
of a sentence, return an empty text for it.
Return JSON: {"fixes": [{"id": 0, "text": "...", "citations": ["p1"]}]}"""

SCHEMA = {
    "type": "object",
    "properties": {"fixes": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "text": {"type": "string"},
                       "citations": {"type": "array", "items": {"type": "string"}}},
        "required": ["id", "text", "citations"]}}},
    "required": ["fixes"],
}


def repair_many(claims: list[Claim], evidence: list[Chunk], related: dict[int, set] | None = None) -> dict[int, Claim | None]:
    """{claim.index: rewritten Claim, or None to drop}. `related` maps claim.index -> evidence labels worth showing
    (cited + best-matching passage); defaults to all evidence."""
    if not claims:
        return {}
    labels = set().union(*(related.get(c.index, set()) for c in claims)) if related else {c.label for c in evidence}
    shown = [c for c in evidence if c.label in labels] or evidence
    listing = "\n".join(f'{i}. "{c.sentence}"' for i, c in enumerate(claims))
    try:
        data = chat_json(SYSTEM, f"Sentences:\n{listing}\n\nPassages:\n\n{evidence_block(shown)}", schema=SCHEMA)
    except Exception:
        return {c.index: None for c in claims}
    valid = {c.label for c in evidence}
    out = {c.index: None for c in claims}
    for fix in data.get("fixes", []):
        i, text = fix.get("id"), str(fix.get("text", "")).strip()
        if not isinstance(i, int) or not 0 <= i < len(claims) or not text:
            continue
        cites = [c.strip("[] ") for c in fix.get("citations", []) if isinstance(c, str)]
        old = claims[i]
        out[old.index] = Claim(index=old.index, sentence=text,
                               citations=[c for c in dict.fromkeys(cites) if c in valid], rounds=old.rounds + 1)
    return out


def repair(claim: Claim, evidence: list[Chunk]) -> Claim | None:
    return repair_many([claim], evidence)[claim.index]
