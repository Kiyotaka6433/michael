"""Citation health: does every quote in Michael's notes still exist, word for word, in the note it cites?

Sources change (you edit a saved article, a page is re-fetched, a note is renamed). Every footnote quote that
points into the vault is looked up again; the result is written to `Michael/Citation check.md`.
"""
import re
from datetime import datetime
from pathlib import Path

from .host.heralds.vault import FRONTMATTER

FOOT = re.compile(r'^\[\^(\d+)\]: "(.*)" - (\[\[([^\]|#]+)(?:#[^\]|]*)?\]\]|\[[^\]]*\]\([^)]*\))', re.M)
_norm = lambda s: re.sub(r"[\s*_`>]+", " ", s).strip().lower()


def recheck_vault(vault: str | Path, on_progress=None) -> dict:
    vault = Path(vault)
    stems = {}
    for p in vault.rglob("*.md"):
        if ".obsidian" not in p.parts:
            stems.setdefault(p.stem, p)
    checked = ok = external = 0
    broken, missing = [], []
    notes = [p for p in vault.rglob("*.md") if ".obsidian" not in p.parts]
    for n, note in enumerate(notes, 1):
        text = note.read_text(encoding="utf8", errors="ignore")
        m = FRONTMATTER.match(text)
        if not m or not re.search(r"(?m)^question:", m.group(0)):
            continue
        for f in FOOT.finditer(text):
            quote, target = f.group(2), f.group(4)
            if not target:
                external += 1                     # web source: checked when the note was written
                continue
            checked += 1
            src = stems.get(target.strip())
            if src is None:
                missing.append((note, target, quote))
                continue
            if _norm(quote)[:300] in _norm(src.read_text(encoding="utf8", errors="ignore")):
                ok += 1
            else:
                broken.append((note, target, quote))
        if on_progress and n % 50 == 0:
            on_progress(f"{n}/{len(notes)} notes scanned, {checked} vault citations checked")
    _report(vault, checked, ok, external, broken, missing)
    return {"checked": checked, "ok": ok, "broken": len(broken), "missing_source": len(missing), "external": external}


def _report(vault: Path, checked, ok, external, broken, missing):
    lines = ["---", "michael: generated", "tags: [michael, health]", "---", "# Citation check", "",
             f"Run {datetime.now():%Y-%m-%d %H:%M}. {checked} quotes pointing into the vault were looked up again: "
             f"**{ok} still match word for word**, {len(broken)} changed, {len(missing)} point to a missing note "
             f"({external} web citations were checked when written).", ""]
    if broken:
        lines += ["## Quote no longer found in its source", ""]
        lines += [f"- [[{n.stem}]] → [[{t}]]: \"{q[:160]}\"" for n, t, q in broken] + [""]
    if missing:
        lines += ["## Source note missing (renamed or deleted?)", ""]
        lines += [f"- [[{n.stem}]] → `{t}`" for n, t, _ in missing] + [""]
    out = vault / "Michael" / "Citation check.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf8")
