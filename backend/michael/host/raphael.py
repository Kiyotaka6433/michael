"""Rewrite unsupported sentences so they say only what the evidence supports, or drop them.
All failed sentences of a round go to the LLM in ONE call, with only the passages they relate to."""
from ..config import settings
from .. import llm
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


QUOTE_RULE = """
Under each sentence is the CLOSEST QUOTE found for it. Prefer rewriting the sentence so it says what that quote
says - shorten the quote if needed but keep its words and their order, and name the subject instead of "it" -
and cite that quote's passage label."""


def repair_many(claims: list[Claim], evidence: list[Chunk], related: dict[int, set] | None = None,
                quotes: dict[int, tuple[str, str]] | None = None) -> dict[int, Claim | None]:
    """{claim.index: rewritten Claim, or None to drop}. `related` maps claim.index -> evidence labels worth showing
    (cited + best-matching passage); defaults to all evidence."""
    if not claims:
        return {}
    labels = set().union(*(related.get(c.index, set()) for c in claims)) if related else {c.label for c in evidence}
    shown = [c for c in evidence if c.label in labels] or evidence
    anchored = bool(settings.quote_repair and quotes)
    lines = []
    for i, c in enumerate(claims):
        lines.append(f'{i}. "{c.sentence}"')
        if anchored and c.index in quotes:           # recall experiment: repair against the exact closest quote
            label, quote = quotes[c.index]
            lines.append(f'   closest quote [{label}]: "{" ".join(quote.split())[:600]}"')
    listing = "\n".join(lines)
    system = SYSTEM + (QUOTE_RULE if anchored else "")
    conv = None
    if settings.repair_in_conversation and (settings.writer_model or settings.llm_model) == settings.llm_model:
        conv = llm.conversation_for({(c.label, c.text) for c in evidence}, settings.llm_model)
    try:
        if conv:
            # continue the writer's conversation: its passages are already in Ollama's prompt cache, so only the
            # instructions, the sentences and any passages found later (claim-driven retrieval) are read
            seen = {label for label, _ in conv["passages"]}
            extra = [c for c in shown if c.label not in seen]
            more = f"\n\nMore passages:\n\n{evidence_block(extra)}" if extra else ""
            data = chat_json("", f"{system}\n\nSentences:\n{listing}{more}", schema=SCHEMA, history=conv["messages"])
        else:
            data = chat_json(system, f"Sentences:\n{listing}\n\nPassages:\n\n{evidence_block(shown)}", schema=SCHEMA)
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
