"""OEIS, the On-Line Encyclopedia of Integer Sequences (free JSON search). Useful for number-theory questions:
each hit gives the sequence name, its first terms, formulas and comments written by mathematicians."""
from ...models import Source
from .http import clean_query, get

API = "https://oeis.org/search"


def search(query: str, n: int = 2) -> list[Source]:
    data = get(API, {"q": clean_query(query), "fmt": "json"}).json()
    results = data.get("results") if isinstance(data, dict) else data
    out = []
    for r in (results or [])[:n]:
        anum = f"A{int(r['number']):06d}"
        parts = [f"{anum}: {r.get('name', '')}.", f"First terms: {r.get('data', '')}."]
        parts += [f"Formula: {f}" for f in r.get("formula", [])[:8]]
        parts += [f"Comment: {c}" for c in r.get("comment", [])[:8]]
        out.append(Source(kind="oeis", title=f"OEIS {anum}: {r.get('name', '')[:80]}", url=f"https://oeis.org/{anum}",
                          text="\n".join(parts)))
    return out
