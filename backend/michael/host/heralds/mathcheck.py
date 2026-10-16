"""Check that LaTeX formulas render in MathJax (Obsidian's math engine), and protect notes from broken math.

Runs tools/mathcheck/check.mjs with Node. If Node or the tool is missing, every formula is reported as
unchecked (None) rather than failed, so ingestion still works.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

TOOL = Path(__file__).resolve().parents[4] / "tools" / "mathcheck" / "check.mjs"

# $$...$$ first, then $...$ (not $$, not escaped \$, no newline inside inline math)
DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
INLINE = re.compile(r"(?<![\\$])\$(?!\$)([^\n$]+?)(?<![\\$])\$(?!\$)")


def available() -> bool:
    return TOOL.exists() and (TOOL.parent / "node_modules").exists() and shutil.which("node") is not None


def check(formulas: list[str]) -> list[str | None] | None:
    """Error message per formula (None = renders). Returns None when the checker is unavailable."""
    if not formulas:
        return []
    if not available():
        return None
    r = subprocess.run(["node", str(TOOL)], input=json.dumps(formulas), capture_output=True, text=True,
                       encoding="utf8", timeout=120)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def find_math(md: str) -> list[tuple[int, int, str, bool]]:
    """(start, end, tex, is_display) for every formula in a Markdown text, skipping code blocks."""
    code = [(m.start(), m.end()) for m in re.finditer(r"```.*?```|`[^`\n]+`", md, re.S)]
    in_code = lambda i: any(s <= i < e for s, e in code)
    found = [(m.start(), m.end(), m.group(1), True) for m in DISPLAY.finditer(md) if not in_code(m.start())]
    taken = [(s, e) for s, e, _, _ in found]
    for m in INLINE.finditer(md):
        if not in_code(m.start()) and not any(s <= m.start() < e for s, e in taken):
            found.append((m.start(), m.end(), m.group(1), False))
    return sorted(found)


# exact equivalents for macros Obsidian's MathJax does not load
EQUIVALENTS = [(re.compile(r"\\bm(?![A-Za-z])"), r"\\boldsymbol"), (re.compile(r"\\bold(?![A-Za-z])"), r"\\mathbf")]


def normalize(md: str) -> str:
    for rx, repl in EQUIVALENTS:
        md = rx.sub(repl, md)
    return md


def guard(md: str) -> tuple[str, dict]:
    """Check every formula; replace those MathJax cannot render with a visible, flagged code span so a
    note never shows silently broken math. Returns (markdown, stats)."""
    md = normalize(md)
    spans = find_math(md)
    errors = check([tex for _, _, tex, _ in spans])
    if errors is None:
        return md, {"formulas": len(spans), "rendered": None, "failed": None, "checked": False}
    out, last, failed = [], 0, 0
    for (s, e, tex, display), err in zip(spans, errors):
        out.append(md[last:s])
        if err is None:
            out.append(md[s:e])
        else:
            failed += 1
            if display:
                out.append(f"\n```latex\n{tex.strip()}\n```\n> [!warning] Formula could not be rendered: {err}\n")
            else:
                out.append(f"`{tex}`⚠")
        last = e
    out.append(md[last:])
    return "".join(out), {"formulas": len(spans), "rendered": len(spans) - failed, "failed": failed, "checked": True}
