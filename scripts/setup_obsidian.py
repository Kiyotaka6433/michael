"""Create (or update) an Obsidian vault with the Michael plugin installed and enabled.

    python scripts/setup_obsidian.py ["C:/path/to/vault"]

Re-run after `npm run build` in obsidian-michael/ to push a new plugin build into the vault.
"""
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "obsidian-michael"
DEFAULT_VAULT = ROOT.parent / "Michael Vault"
MICHAEL_EXE = ROOT / ".venv" / "Scripts" / "michael.exe"

WELCOME = """# Welcome to Michael

Michael writes research notes where **every sentence is backed by an exact quote** from a source,
checked by an independent verifier. Sentences that fail are rewritten or removed.

## How to use
1. Click the **search-check icon** in the left ribbon, or press `Ctrl+P` and run **Michael: Research a question**.
2. Type a question, optionally paste extra web pages (one URL per line), press Enter.
3. Watch progress in the status bar (bottom right). The note opens by itself in the `Michael/` folder.

Other commands (`Ctrl+P`):
- **Michael: Research the selected text** - select a question in any note first.
- **Michael: Verify selected sentence against the clipboard text** - fact-check one sentence.
- **Michael: Start the backend** - if the status bar says "backend offline".

## Reading a Michael note
- `[^1]` footnotes hold the exact quote, the source link and the verifier score.
- The **Trust panel** at the top shows how many sentences were verified.
- **Removed claims** lists what the model wrote but could not prove.

## Your notes are a source too
Everything in this vault (except the `Michael/` folder) is searched alongside Wikipedia, arXiv and OpenAlex,
and cited as `[[Note#Heading]]` links. Try the sample in `Networking/`.

## Requirements
- Ollama running with `qwen2.5:3b` (`ollama pull qwen2.5:3b`).
- The backend starts automatically when Obsidian opens (Settings -> Michael to change).
"""

SAMPLE = """---
tags: [networking, sample]
---
# Link aggregation

## LACP
LACP (Link Aggregation Control Protocol) is defined in IEEE 802.3ad, now 802.1AX.
It is an open standard, so it works between switches from different vendors.
Modes: **active** (sends LACPDUs) and **passive** (only answers).

## PAgP
PAgP (Port Aggregation Protocol) is Cisco proprietary.
Modes: **desirable** (starts negotiation) and **auto** (only answers).

## My lab notes
In the NirmaTech Packet Tracer lab the distribution switches use an EtherChannel to the core.
"""


def register_vault(vault: Path):
    """Add the vault to Obsidian's vault list so it shows up (and opens) on launch."""
    cfg_path = Path(os.environ["APPDATA"]) / "obsidian" / "obsidian.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf8")) if cfg_path.exists() else {}
    vaults = cfg.setdefault("vaults", {})
    for v in vaults.values():
        v.pop("open", None)
    vid = next((k for k, v in vaults.items() if Path(v["path"]) == vault), secrets.token_hex(8))
    vaults[vid] = {"path": str(vault), "ts": int(time.time() * 1000), "open": True}
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf8")


def main():
    vault = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_VAULT
    obs = vault / ".obsidian"
    dest = obs / "plugins" / "michael"
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("main.js", "manifest.json", "styles.css"):
        shutil.copy2(PLUGIN / f, dest / f)

    data = dest / "data.json"                       # plugin settings: point it at this project's backend
    settings = json.loads(data.read_text(encoding="utf8")) if data.exists() else {}
    settings["backendCommand"] = MICHAEL_EXE.as_posix()
    data.write_text(json.dumps(settings, indent=2), encoding="utf8")

    cp = obs / "community-plugins.json"
    enabled = json.loads(cp.read_text(encoding="utf8")) if cp.exists() else []
    if "michael" not in enabled:
        enabled.append("michael")
    cp.write_text(json.dumps(enabled), encoding="utf8")

    if not (vault / "Welcome to Michael.md").exists():
        (vault / "Welcome to Michael.md").write_text(WELCOME, encoding="utf8")
        (vault / "Networking").mkdir(exist_ok=True)
        (vault / "Networking" / "Link aggregation.md").write_text(SAMPLE, encoding="utf8")
        (vault / "Michael").mkdir(exist_ok=True)

    register_vault(vault)
    print(f"vault ready: {vault}")
    print(f"plugin installed: {dest}")


if __name__ == "__main__":
    main()
