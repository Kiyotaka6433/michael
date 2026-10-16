"""Question -> 2-3 focused search queries (each query costs a request to every source)."""
from ..llm import chat_json

SYSTEM = ("You plan web and literature searches. Return JSON {\"queries\": [..]} with 2 or 3 short keyword "
          "queries that together cover every part of the user's question. Comparisons need one query per side.")


def plan(question: str) -> list[str]:
    try:
        queries = chat_json(SYSTEM, question).get("queries", [])
    except Exception:
        queries = []
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()][:3]
    return [question] + [q for q in queries if q.lower() != question.lower()]
