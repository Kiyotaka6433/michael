"""Minimal Ollama client that always asks for JSON output."""
import json
import re

import httpx

from . import db
from .config import settings
from .models import sha


class LLMUnavailable(RuntimeError):
    pass


_available = {"t": 0.0, "ok": False}


def available() -> bool:
    """Is the writing model installed? Cached for a minute: /health is polled by the extension and the plugin, and
    a busy Ollama (generating a note) answers /api/tags slowly - the status must not wait for it."""
    import time
    if time.time() - _available["t"] < 60:
        return _available["ok"]
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3)
        names = [m["name"] for m in r.json().get("models", [])]
        ok = any(n == settings.llm_model or n.startswith(settings.llm_model + ":") for n in names)
    except Exception:
        ok = _available["ok"] and time.time() - _available["t"] < 600     # one slow answer isn't "offline"
    _available.update(t=time.time(), ok=ok)
    return ok


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


LAST_STATS: dict = {}       # timings of the last uncached call (tokens and nanoseconds, from Ollama)


# The writer's last conversations, so a repair can CONTINUE one: Ollama keeps the conversation's tokens in its prompt
# cache, so the repair reads only its new instructions instead of the whole evidence again (speed).
CONVERSATIONS: list[dict] = []
LAST_REPLY: dict = {"text": None}    # the raw text of the last generated answer (None when it came from the cache)


def remember_conversation(passages: set, model: str, messages: list[dict], reply: str):
    CONVERSATIONS.append({"passages": passages, "model": model,
                          "messages": messages + [{"role": "assistant", "content": reply}]})
    del CONVERSATIONS[:-4]


def conversation_for(passages: set, model: str) -> dict | None:
    """The newest writer conversation that showed only passages from `passages` (same label, same text)."""
    return next((c for c in reversed(CONVERSATIONS) if c["model"] == model and c["passages"] <= passages), None)


def prefill(system: str, model: str):
    """Fire-and-forget: Ollama reads `system` into its prompt cache (one token generated), so the next call that
    starts with the same system prompt skips reading it. Never blocks the caller; errors are ignored."""
    import threading

    def go():
        try:
            httpx.post(f"{settings.ollama_url}/api/chat", timeout=300, json={
                "model": model, "stream": False, "keep_alive": "30m", "options": {**_options(0.1), "num_predict": 1},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": ""}]})
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def chat_text(system: str, user: str, temperature: float = 0.1, model: str | None = None,
              history: list[dict] | None = None) -> str:
    """Free-text answer (no JSON, no constrained decoding: fewer tokens to generate)."""
    return _chat(system, user, temperature, None, model, history)["text"]


def chat_json(system: str, user: str, temperature: float = 0.1, retries: int = 2, schema: dict | None = None,
              model: str | None = None, history: list[dict] | None = None) -> dict:
    """`schema` (a JSON Schema) makes Ollama constrain decoding to exactly that shape. `history`: earlier messages
    of the conversation (then `system` is not sent again)."""
    return _chat(system, user, temperature, schema or "json", model, history, retries)


def _chat(system, user, temperature, fmt, model, history, retries=2):
    messages = (history or [{"role": "system", "content": system}]) + [{"role": "user", "content": user}]
    payload = {"model": model or settings.llm_model, "stream": False, "keep_alive": "30m",
               "options": _options(temperature), "messages": messages}
    if fmt:
        payload["format"] = fmt
    key = sha(json.dumps([payload["model"], fmt, payload["options"]["temperature"], messages], sort_keys=True))
    LAST_REPLY["text"] = None
    if settings.llm_cache and (cached := db.cache_get("llm", [key]).get(key)):   # same prompt -> same answer, instantly
        return cached
    last = None
    for _ in range(retries + 1):
        try:
            r = httpx.post(f"{settings.ollama_url}/api/chat", json=payload, timeout=1200)
            r.raise_for_status()
            body = r.json()
            # where the time goes on CPU: reading the prompt vs generating the answer (Ollama reports both)
            LAST_STATS.update({k: body.get(k, 0) for k in ("prompt_eval_count", "prompt_eval_duration",
                                                            "eval_count", "eval_duration", "total_duration")})
            if settings.extra.get("trace") is not None:          # eval/profile_note.py: per-call token counts
                settings.extra["trace"].append({k: body.get(k, 0) for k in ("prompt_eval_count", "prompt_eval_duration",
                                                                            "eval_count", "eval_duration")})
            content = body["message"]["content"]
            LAST_REPLY["text"] = content
            data = repair_latex(json.loads(content)) if fmt else {"text": content}
            db.cache_put("llm", {key: data})
            return data
        except httpx.ConnectError as e:
            raise LLMUnavailable(f"Ollama is not reachable at {settings.ollama_url}. Install it and run "
                                 f"`ollama pull {settings.llm_model}`.") from e
        except (json.JSONDecodeError, KeyError, httpx.HTTPStatusError, httpx.TimeoutException) as e:   # busy CPU: retry
            last = e
    raise LLMUnavailable(f"LLM did not return valid JSON: {last}")
