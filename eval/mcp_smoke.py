"""End-to-end check of the MCP server the way an AI client uses it: start `python -m michael.mcp_server` over stdio,
list its tools, and call search_library and check_facts.

    python eval/mcp_smoke.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "michael.mcp_server"], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            t = time.time()
            r = await session.call_tool("search_library", {"query": "Fenwick tree prefix sums", "k": 3})
            print(f"search_library {time.time() - t:.1f}s:", r.content[0].text[:300].replace("\n", " "), "...")
            t = time.time()
            r = await session.call_tool("check_facts", {"text": (
                "A Fenwick tree can compute prefix sums in logarithmic time. "
                "The Euclidean algorithm was first described by Isaac Newton in 1687.")})
            out = json.loads(r.content[0].text)
            print(f"check_facts {time.time() - t:.1f}s:", out["summary"])
            for s in out["sentences"]:
                print(f"   {s['verdict']:11s} {s['sentence'][:70]} <- {s.get('source', '')[:60]}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
