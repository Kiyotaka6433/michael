"""Vault watcher: keeps the index in step with the files. The file always wins.

Edits made in Obsidian (or by Michael's own jobs) are picked up within a few seconds and only the changed notes are
re-indexed. Changes are debounced, which also rides out OneDrive's bursts of sync writes.
"""
import threading
from pathlib import Path

_threads: dict[str, threading.Thread] = {}
_stop = threading.Event()
listeners = []                                   # callables(event dict) - the API forwards these to clients


def _only_markdown(change, path: str) -> bool:
    p = Path(path)
    return p.suffix == ".md" and ".obsidian" not in p.parts and ".trash" not in p.parts


def _loop(vault: str):
    from watchfiles import watch
    from . import vault_index
    for changes in watch(vault, watch_filter=_only_markdown, debounce=3000, step=500, stop_event=_stop,
                         raise_interrupt=False):
        try:
            result = vault_index.index_vault(vault)
            event = {"stage": "vault-changed", "detail": f"{len(changes)} file changes", **result,
                     "files": sorted({Path(p).name for _, p in changes})[:20]}
            for fn in list(listeners):
                fn(event)
        except Exception as e:                      # never let the watcher die on one bad file
            print(f"watcher: {e}")


def watch_vault(vault: str | None):
    """Start watching a vault (once per vault, in the background)."""
    if not vault or not Path(vault).is_dir():
        return False
    key = str(Path(vault).resolve())
    if key in _threads and _threads[key].is_alive():
        return True
    t = threading.Thread(target=_loop, args=(key,), name=f"michael-watch", daemon=True)
    t.start()
    _threads[key] = t
    return True


def stop():
    _stop.set()
