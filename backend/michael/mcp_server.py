"""Michael as an MCP server: any AI assistant (Claude Code, Claude Desktop, ...) can fact-check text against your
trusted library with Michael's verifier, search the library, read notes and run evidence-locked research.

A thin client of the running Michael backend (models stay loaded there, once); starts the backend if it isn't up.

    michael-mcp                      (stdio; see .mcp.json in the repo for Claude Code)
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

BACKEND = os.getenv("MICHAEL_URL", "http://127.0.0.1:8765")
SLOW = 900          # fact-checking a long answer against the library can take minutes on a laptop CPU

server = MCPServer(
    name="michael",
    title="Michael - evidence-locked research",
    instructions=(
        "Michael checks claims against the user's own library of saved trusted sources (Wikipedia, cp-algorithms, "
        "Princeton Algorithms, Stanford notes, CS231n, papers ...) with an independent NLI verifier, and returns the "
        "exact quote that supports each sentence. Use check_facts to verify any text (including your own answers) "
        "before presenting it as fact; report UNSUPPORTED sentences as unverified, and cite the quotes/sources "
        "returned. Use search_library and read_note to look things up in the library."),
)


def _backend_up() -> bool:
    try:
        return httpx.get(f"{BACKEND}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def _ensure_backend():
    """Start `michael serve` (from this project's venv) if nothing answers, and wait for it."""
    if _backend_up():
        return
    exe = Path(sys.executable).with_name("michael.exe" if os.name == "nt" else "michael")
    # The backend is shared with Obsidian and the browser extension, so it must outlive this MCP session - but an MCP
    # client ends its server's whole process tree (on Windows a job object, which a child can't always leave) when
    # the session closes. On Windows, Win32_Process.Create starts it from the WMI service: never part of our job.
    root = str(Path(__file__).resolve().parents[2])
    port = BACKEND.rsplit(":", 1)[-1]
    if os.name == "nt":
        cmd = f'"{exe}" serve --port {port}'
        ps = (f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
              f"@{{CommandLine='{cmd}'; CurrentDirectory='{root}'}} | Out-Null")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen([str(exe), "serve", "--port", port], cwd=root, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    for _ in range(90):
        time.sleep(2)
        if _backend_up():
            return
    raise RuntimeError(f"The Michael backend did not start at {BACKEND}. Run `michael serve` in the project folder.")


def _get(path: str, **params):
    _ensure_backend()
    r = httpx.get(f"{BACKEND}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=120)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict, timeout: float = 120):
    _ensure_backend()
    r = httpx.post(f"{BACKEND}{path}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


@server.tool()
def check_facts(text: str, evidence: str | None = None, subject: str | None = None) -> dict:
    """Fact-check a text sentence by sentence with Michael's independent verifier.

    Without `evidence`, every sentence is checked against the user's library of trusted sources (only saved source
    articles, never Michael's own generated notes). With `evidence`, it is checked against that text instead.
    Each sentence gets a verdict - SUPPORTED (a quote proves it), PARTIAL (related but not proven) or UNSUPPORTED -
    plus the exact quote, the source note and its original URL. Optional `subject`: "Number Theory",
    "DSA and Competitive Programming" or "Machine Learning". Up to 40 sentences; can take a few minutes.
    """
    r = _post("/api/v1/check", {"text": text, "evidence": evidence, "subject": subject}, timeout=SLOW)
    for s in r["sentences"]:
        if s["verdict"] == "UNSUPPORTED":
            s.pop("quote", None)               # the closest passage of an unsupported sentence would only mislead
    return r


@server.tool()
def search_library(query: str, k: int = 8, subject: str | None = None) -> list[dict]:
    """Search the user's library (saved trusted articles) by meaning and keywords. Returns the best passages with
    their note, section, original URL and text."""
    res = _get("/api/v1/search", q=query, k=min(k, 20), subject=subject, include_generated="false")["results"]
    return [{"note": r["rel"], "title": r["title"], "section": r["heading"], "subject": r["subject"],
             "url": r.get("url") or "", "text": r["text"][:1200]} for r in res]


@server.tool()
def read_note(path: str) -> dict:
    """Read one note of the library by its vault path (as returned by search_library, e.g.
    "Number Theory/Sources/Euclidean algorithm.md"): its Markdown, frontmatter and backlinks."""
    r = _get("/api/v1/note", path=path)
    r["markdown"] = r.get("markdown", "")[:30000]
    return r


@server.tool()
def verified_facts(query: str | None = None, source: str | None = None, subject: str | None = None,
                   limit: int = 20) -> list[dict]:
    """Facts Michael has already verified in its notes (each with the exact supporting quote and source).
    Filter by words in the fact (`query`), by source note title (`source`) or by `subject`."""
    r = _get("/api/v1/claims", status="supported", q=query, source=source, subject=subject, limit=min(limit, 100))
    return [{"fact": c["sentence"], "quote": c["quote"], "source": c["source"], "note": c.get("rel") or c["path"]}
            for c in r["claims"]]


@server.tool()
def research_start(question: str) -> dict:
    """Start an evidence-locked research note on a question (searches the library and free sources, writes a note
    in which every sentence cites a verified quote). Takes several minutes; poll research_result with the run_id."""
    return _post("/research", {"question": question})


@server.tool()
def research_result(run_id: str) -> dict:
    """Status of a research run; when finished, the note (Markdown with footnoted quotes) and its trust stats."""
    r = _get(f"/runs/{run_id}")
    out = {"status": r.get("status"), "question": r.get("question"), "stats": r.get("stats"), "note": r.get("note_path")}
    if r.get("status") in ("done", "finished", "complete") or r.get("markdown"):
        out["markdown"] = (r.get("markdown") or "")[:30000]
    if r.get("error"):
        out["error"] = r["error"]
    return out


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
