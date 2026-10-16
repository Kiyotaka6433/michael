"""Minimal Ollama client that always asks for JSON output."""
import json

import httpx

from .config import settings


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


def chat_json(system: str, user: str, temperature: float = 0.1, retries: int = 2, schema: dict | None = None) -> dict:
    """`schema` (a JSON Schema) makes Ollama constrain decoding to exactly that shape."""
    payload = {"model": settings.llm_model, "stream": False, "format": schema or "json", "keep_alive": "30m",
               "options": _options(temperature),
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    last = None
    for _ in range(retries + 1):
        try:
            r = httpx.post(f"{settings.ollama_url}/api/chat", json=payload, timeout=600)
            r.raise_for_status()
            return json.loads(r.json()["message"]["content"])
        except httpx.ConnectError as e:
            raise LLMUnavailable(f"Ollama is not reachable at {settings.ollama_url}. Install it and run "
                                 f"`ollama pull {settings.llm_model}`.") from e
        except (json.JSONDecodeError, KeyError, httpx.HTTPStatusError) as e:
            last = e
    raise LLMUnavailable(f"LLM did not return valid JSON: {last}")
