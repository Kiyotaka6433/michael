"""Try extracting candidate pages WITHOUT saving them: prints route, size, formula count and title, so only sites
that extract cleanly are added to the library.

    python scripts/probe_sources.py URL [URL ...]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from michael.host import pravuil   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
for url in sys.argv[1:]:
    try:
        a = pravuil.fetch(url)
        md = a.markdown
        maths = len(re.findall(r"\$[^$]+\$", md))
        code = md.count("```") // 2
        print(f"OK   {len(md):7d} chars {maths:4d} math {code:3d} code  {a.route:10s} {a.title[:60]}  <- {url}")
        print("     " + " ".join(md[:3000].split())[600:900])
    except Exception as e:
        print(f"FAIL {url}: {str(e)[:120]}")
