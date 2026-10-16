"""Shared HTTP helpers: polite User-Agent, per-host rate limits, retries with back-off on 429/5xx."""
import re
import threading
import time

import httpx

from ...config import settings

MIN_INTERVAL = {"export.arxiv.org": 3.1, "arxiv.org": 3.1,     # arXiv terms: one request every 3 seconds
                "api.semanticscholar.org": 1.1, "api.stackexchange.com": 0.2, "oeis.org": 0.5}
_last: dict[str, float] = {}
_lock = threading.Lock()


def client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": settings.user_agent})


def clean_query(q: str) -> str:
    """Keep words, numbers, dots and hyphens; search APIs reject or mis-parse other punctuation."""
    return " ".join(re.sub(r"[^\w.\-]+", " ", q).split())


def _throttle(url: str):
    host = httpx.URL(url).host
    gap = MIN_INTERVAL.get(host, 0)
    if not gap:
        return
    with _lock:
        wait = _last.get(host, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()


_down: dict[str, float] = {}          # host -> time it was found unreachable
DOWN_FOR = 300                        # skip an unreachable host for 5 minutes instead of retrying it


class HostDown(RuntimeError):
    pass


def get(url: str, params: dict | None = None, retries: int = 3) -> httpx.Response:
    """Retries only what retrying can fix (429, 5xx, timeouts). DNS/connection/SSL failures mean the network or
    the host is down: fail at once and remember it, so one dead source cannot stall a run for minutes."""
    host = httpx.URL(url).host
    if time.time() - _down.get(host, 0) < DOWN_FOR:
        raise HostDown(f"{host} was unreachable a moment ago; skipped")
    delay = 4.0
    with client() as c:
        for attempt in range(retries + 1):
            _throttle(url)
            try:
                r = c.get(url, params=params)
            except (httpx.ConnectError, httpx.RemoteProtocolError) as e:   # DNS, refused, reset, SSL
                _down[host] = time.time()
                raise HostDown(f"{host} unreachable: {e}") from e
            except httpx.TimeoutException:
                if attempt == retries:
                    _down[host] = time.time()
                    raise
            else:
                if r.status_code not in (429, 500, 502, 503, 504):
                    r.raise_for_status()
                    return r
                if attempt == retries:
                    r.raise_for_status()
                ra = r.headers.get("retry-after", "")
                if ra.isdigit():
                    delay = max(delay, float(ra))
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")
