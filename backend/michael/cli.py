"""Command line.

  michael search "LACP vs PAgP"            retrieval only (no LLM): gather, hybrid search, rerank
  michael ask "How does LACP differ from PAgP?" [--url URL] [--pdf FILE] [--no-vault]
  michael add https://arxiv.org/abs/1706.03762 [--vault PATH] [--no-summary]   save an article (+ key points)
  michael verify "sentence" "evidence text"
  michael serve [--port 8765]
"""
import argparse
import json
import sys


def _print_event(e):
    print(f"[{e['t']:6.1f}s] {e['stage']:<8} {e['detail']}", flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(prog="michael", description="Evidence-locked research agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="retrieval only: show the evidence the writer would get")
    s.add_argument("question")
    s.add_argument("--no-rerank", action="store_true")
    s.add_argument("--sources", nargs="*", default=None)

    a = sub.add_parser("ask", help="full run: write, verify, repair, export a note")
    a.add_argument("question")
    a.add_argument("--url", action="append", default=[])
    a.add_argument("--pdf", action="append", default=[])
    a.add_argument("--sources", nargs="*", default=None)
    a.add_argument("--no-vault", action="store_true")
    a.add_argument("--no-repair", action="store_true")

    ad = sub.add_parser("add", help="save an article (web, arXiv, PDF) with exact LaTeX, plus verified key points")
    ad.add_argument("target", help="URL, arXiv link or id, PDF URL or path")
    ad.add_argument("--vault", default=None, help="vault to save into (default: MICHAEL_VAULT, else data/notes)")
    ad.add_argument("--no-summary", action="store_true", help="only save the article, no key-points note")

    v = sub.add_parser("verify", help="check one sentence against evidence text")
    v.add_argument("sentence")
    v.add_argument("evidence")

    sv = sub.add_parser("serve", help="start the API for the Obsidian plugin and dashboard")
    sv.add_argument("--port", type=int, default=8765)

    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "search":
        from . import db
        from .host.archangel import EMBEDDER, RERANKER, collect_candidates
        from .host.jophiel import hybrid_search
        db.init()
        chunks = collect_candidates(args.question, [args.question], args.sources, emit=lambda st, d="", **k: print(f"{st}: {d}"))
        cands = hybrid_search([args.question], chunks, EMBEDDER)
        top = cands[:8] if args.no_rerank else RERANKER.rerank(args.question, cands)
        for i, c in enumerate(top, 1):
            print(f"\n[p{i}] {c.score:+.3f}  {c.kind}: {c.title}{' #' + c.heading if c.heading else ''}\n     {c.url}")
            print("     " + " ".join(c.text.split())[:300])
    elif args.cmd == "ask":
        from .host.archangel import run_research
        res = run_research(args.question, kinds=args.sources, urls=args.url, pdfs=args.pdf,
                           use_vault=not args.no_vault, repair_enabled=not args.no_repair, on_event=_print_event)
        print(f"\nNote written to {res['note']}\n")
        print(res["markdown"])
    elif args.cmd == "add":
        from .config import settings
        from .host.pravuil import add_article
        res = add_article(args.target, summary=not args.no_summary, vault_path=args.vault or settings.vault_path,
                          on_event=_print_event)
        print(f"\nArticle saved to {res['source_note']}")
        if res["note"]:
            print(f"Key points written to {res['note']}\n")
            print(res["markdown"])
    elif args.cmd == "verify":
        from .host.archangel import verify_text
        print(json.dumps(verify_text(args.sentence, args.evidence), indent=2))
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("michael.api:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
