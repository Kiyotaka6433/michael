"""Render the verified answer as an Obsidian note: footnoted quotes, a trust panel and a source list."""
import re
from datetime import datetime

from ..models import Chunk, Claim, Verdict

ICON = {"SUPPORTED": "", "PARTIAL": " ⚠", "UNSUPPORTED": " ✗"}


def slugify(text: str, n: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text).strip()
    return re.sub(r"\s+", " ", s)[:n] or "Michael note"


def _yaml(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def render(question: str, claims: list[Claim], verdicts: dict[int, Verdict], evidence: list[Chunk],
           removed: list[Claim], model: str, stats: dict) -> str:
    by_id = {c.id: c for c in evidence}
    by_label = {c.label: c for c in evidence}
    used = []
    body, notes = [], []
    for n, claim in enumerate(claims, 1):
        v = verdicts.get(claim.index)
        text = claim.sentence
        if v and v.label == "PARTIAL":
            text = f"=={text}=="
        if v and v.quote:
            chunk = by_id[v.chunk_id]
            if chunk.id not in used:
                used.append(chunk.id)
            quote = " ".join(v.quote.split())
            ctx = " in the context of its paragraph" if getattr(v, "in_context", False) else ""
            ctx += {"match": " · formulas and numbers checked", "proven": " · formulas proven equivalent"}.get(getattr(v, "math", ""), "")
            if getattr(v, "parts", 0):
                ctx += f" · proven in {v.parts} parts"
            if getattr(v, "titled", False):
                ctx += " · judged with its source title as context"
            note = f'[^{n}]: "{quote}" - {chunk.link} · {v.label.lower()}{ctx} (entailment {v.entailment:.2f})'
            other = by_label.get(getattr(v, "conflict_label", ""))
            if other is not None:            # shown, never resolved silently: the reader sees both quotes
                note += (f' · ⚠ {other.link} appears to disagree: "{" ".join(v.conflict_quote.split())}"'
                         f" (contradiction {v.conflict_score:.2f})")
            notes.append(note)
            body.append(f"{text}[^{n}]{ICON[v.label]}" + (" ⚠" if other is not None else ""))
        else:
            body.append(f"{text}{ICON['UNSUPPORTED']}")

    s = stats
    panel = (f"> [!info] Trust panel\n"
             f"> **{s['supported']}/{s['total']}** sentences verified · {s['partial']} partial · "
             f"{s['unsupported']} unsupported · {s['removed']} removed by repair\n"
             f"> Verifier: independent NLI model · writer: `{model}` · {len(used)} sources cited")
    lines = ["---", f"question: {_yaml(question)}", f"created: {datetime.now().isoformat(timespec='seconds')}",
             "tags: [michael]", f"verified: {s['supported']}", f"total: {s['total']}", f"model: {_yaml(model)}", "---",
             f"# {question}", "", panel, "", " ".join(body), ""]
    if removed:
        lines += ["## Removed claims", "Sentences the writer produced but the verifier could not support:", ""]
        lines += [f"- ~~{c.sentence}~~" for c in removed] + [""]
    lines += ["## Sources", ""]
    entries = [f"- {by_id[cid].link}{' - ' + by_id[cid].heading if by_id[cid].heading and by_id[cid].kind != 'vault' else ''}"
               for cid in used]
    lines += list(dict.fromkeys(entries)) + [""]          # two chunks of one section = one source line
    lines += notes
    return "\n".join(lines) + "\n"
