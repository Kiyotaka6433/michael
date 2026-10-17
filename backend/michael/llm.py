"""Minimal Ollama client that always asks for JSON output."""
import json
import re

import httpx

from . import db
from .config import settings
from .models import sha


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3)
        names = [m["name"] for m in r.json().get("models", [])]
        return any(n == settings.llm_model or n.startswith(settings.llm_model + ":") for n in names)
    except Exception:
        return False


def _options(temperature: float) -> dict:
    # every logical core: measured 1.7x faster than Ollama's default on a 4-core/8-thread laptop CPU.
    # The same options on every call, so Ollama never reloads the model between calls.
    return {"temperature": temperature, "num_ctx": settings.llm_ctx, "num_thread": settings.llm_threads}


def warm_up():
    """Load the model into memory and keep it there for 30 minutes."""
    try:
        httpx.post(f"{settings.ollama_url}/api/generate", timeout=120,
                   json={"model": settings.llm_model, "prompt": "", "keep_alive": "30m", "options": _options(0.1)})
    except Exception:
        pass


_ESCAPES = {"\t": "t", "\f": "f", "\b": "b", "\r": "r", "\n": "n", "\v": "v", "\a": "a"}
_LATEX_BROKEN = re.compile(r"[\t\f\b\r\n\v\a](?=[a-zA-Z]{2})")


def repair_latex(value):
    """Models write LaTeX like "\\frac" or "\\text" inside JSON strings without escaping the backslash, so the JSON
    parser turns "\\t" into a tab and "\\f" into a form feed. Control characters directly followed by letters
    never occur in a sentence, so turn them back into backslash commands. Works on nested dicts/lists."""
    if isinstance(value, str):
        return _LATEX_BROKEN.sub(lambda m: "\\" + _ESCAPES[m.group()], value) if "$" in value or "\\" in value \
            or any(c in value for c in "\t\f\b\v\a") else value
    if isinstance(value, list):
        return [repair_latex(v) for v in value]
    if isinstance(value, dict):
        return {k: repair_latex(v) for k, v in value.items()}
    return value


def chat_json(system: str, user: str, temperature: float = 0.1, retries: int = 2, schema: dict | None = None) -> dict:
    """`schema` (a JSON Schema) makes Ollama constrain decoding to exactly that shape."""
    payload = {"model": settings.llm_model, "stream": False, "format": schema or "json", "keep_alive": "30m",
               "options": _options(temperature),
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    key = sha(json.dumps([payload["model"], payload["format"], payload["options"]["temperature"],
                          payload["messages"]], sort_keys=True))
    if cached := db.cache_get("llm", [key]).get(key):     # identical prompt -> identical answer, instantly
        return cached
    last = None
    for _ in range(retries + 1):
        try:
            r = httpx.post(f"{settings.ollama_url}/api/chat", json=payload, timeout=1200)
            r.raise_for_status()
            data = repair_latex(json.loads(r.json()["message"]["content"]))
            db.cache_put("llm", {key: data})
            return data
        except httpx.ConnectError as e:
            raise LLMUnavailable(f"Ollama is not reachable at {settings.ollama_url}. Install it and run "
                                 f"`ollama pull {settings.llm_model}`.") from e
        except (json.JSONDecodeError, KeyError, httpx.HTTPStatusError, httpx.TimeoutException) as e:   # busy CPU: retry
            last = e
    raise LLMUnavailable(f"LLM did not return valid JSON: {last}")
