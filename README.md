# Michael - evidence-locked research agent for Obsidian

Ask a question; Michael gathers free sources (Wikipedia, arXiv, OpenAlex, your own Obsidian vault, any URL or PDF), writes a short note in which **every sentence cites an exact quote**, and has an **independent NLI model** (not the writing LLM) check each sentence against its quote. Unsupported sentences are rewritten or removed, and the note shows a trust panel ("14/16 sentences verified").

Everything runs locally and costs nothing.

```
question → plan queries → gather sources (+ your vault) → chunk + embed (cached)
        → hybrid search (BM25 + embeddings, top 30) → cross-encoder rerank (best 8)
        → write with [pN] citations → locate exact quotes → NLI verify
        → repair or drop unsupported sentences (≤ 2 rounds) → Obsidian note + SQLite record
```

## Project layout

| Path | What it is |
|---|---|
| `backend/michael/` | Python package: `host/` (every stage, see below), `api.py` (FastAPI), `cli.py`, `db.py` (SQLite), `llm.py` (Ollama client), `config.py` |
| `obsidian-michael/` | Obsidian plugin (TypeScript): research command, progress in the status bar, note creation, sentence verification |
| `dashboard/` | Next.js dashboard: start runs, run history and charts, claim-by-claim review with right/wrong labels |
| `eval/` | Evaluation: verifier accuracy/F1 (SciFact + hand-made set), citation precision/recall from your labels, reranker ablation |
| `tests/` | Offline tests (no network, no model downloads) |
| `Michael-Plan.md` | The full project plan |

### The host (pipeline stages)

Michael is an archangel, so each stage in `backend/michael/host/` is named after the angel whose traditional role matches its job.

| Module | Angel | Role | Stage |
|---|---|---|---|
| `archangel.py` | Michael | commander of the host | orchestrates the whole run |
| `chamuel.py` | Chamuel | the seeker | plans search queries from the question |
| `heralds/` | heralds | bring news | source fetchers: Wikipedia, arXiv, OpenAlex, web, PDF, vault |
| `scrolls.py` | — | scrolls | splits sources into passages with exact offsets |
| `jophiel.py` | Jophiel | wisdom | hybrid BM25 + dense search (RRF) |
| `zadkiel.py` | Zadkiel | discernment | cross-encoder reranker |
| `metatron.py` | Metatron | celestial scribe | LLM writer with `[pN]` citations |
| `uriel.py` | Uriel | light of God | finds the exact supporting quote |
| `raguel.py` | Raguel | justice | independent NLI verifier |
| `raphael.py` | Raphael | the healer | repairs or drops unsupported sentences |
| `gabriel.py` | Gabriel | the messenger | renders the Obsidian note |
| `pravuil.py` | Pravuil | keeper of the heavenly records | adds articles to the vault and writes verified key points |

## Setup (Windows, CPU only)

1. Install Ollama and pull the writing model:

```bash
winget install Ollama.Ollama
```

```bash
ollama pull qwen2.5:3b
```

2. Python environment (already created in `.venv` if you used the skeleton as delivered):

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -e ".[dev]"
```

3. Optional, CLI only: use your Obsidian vault as a source (the plugin sends its own vault automatically):

```powershell
$env:MICHAEL_VAULT = "C:\path\to\your\vault"
```

4. For adding articles with exact LaTeX: pandoc, and the MathJax checker (Node):

```bash
winget install JohnMacFarlane.Pandoc
```

```bash
cd tools/mathcheck && npm install
```

The first run downloads the embedding model (≈130 MB), the reranker (≈1.1 GB) and the NLI verifier (≈740 MB) from Hugging Face; later runs reuse them.

## Use

Retrieval only (works without Ollama; shows what evidence the writer would get):

```bash
.venv\Scripts\michael search "How does LACP differ from PAgP?"
```

Full run from the command line (needs Ollama):

```bash
.venv\Scripts\michael ask "How does LACP differ from PAgP?"
```

Check one sentence against a piece of text:

```bash
.venv\Scripts\michael verify "PAgP is an IEEE standard." "PAgP is a Cisco proprietary protocol."
```

API for the plugin and dashboard:

```bash
.venv\Scripts\michael serve
```

Dashboard (in another terminal):

```bash
cd dashboard && npm run dev
```

### Adding articles (with LaTeX)

```bash
.venv\Scripts\michael add https://arxiv.org/abs/1706.03762 --vault "C:\path\to\vault"
```

Michael saves the article verbatim to `Sources/<title>.md` (no LLM touches it) and, unless `--no-summary`, writes `Michael/<title> - key points.md` where every point cites a quote from the saved article as `[[Title#Section]]` and is checked by the verifier. Saved articles are then a source for later questions.

Each article goes through the most exact route available, and the note records which one was used:

| Input | Route | Math |
|---|---|---|
| arXiv link or id | author's LaTeX source → pandoc (sandboxed) | exact |
| arXiv, no source | arXiv HTML (LaTeXML alt-text) | exact |
| web page | formulas recovered from MathML alt-text / TeX annotations / MathJax scripts | exact where the page has TeX |
| PDF | text layer | not reliable, flagged |

Every formula is then checked with MathJax (Obsidian's math engine, `tools/mathcheck`). A formula that would not render is shown as a flagged `latex` code block instead of broken math, and the count goes into the note's frontmatter (`formulas`, `formulas_rendered`).

### Subject library

`library/manifest.json` is a curated reading list (Number Theory, DSA and Competitive Programming, Machine Learning; about 180 articles from Wikipedia, cp-algorithms, the scikit-learn user guide, d2l.ai and landmark arXiv papers). Build it into the vault:

```bash
.venv\Scripts\python scripts/build_library.py fetch
```

```bash
.venv\Scripts\python scripts/build_library.py hubs
```

```bash
.venv\Scripts\python scripts/build_library.py keypoints
```

`fetch` saves every article verbatim with exact math (seconds each), `hubs` writes `Home.md` and one hub note per subject (topics → articles → key points) and adds a "Related" section to each article (nearest articles by embedding, across subjects), and `keypoints` writes a verified key-points note per article (minutes each; resumable, progress in `library/state.json`). The saved articles are a source for every later question; Michael's own notes (key points, answers, hubs) never are.

### Search sources

| Source | What it adds | Default |
|---|---|---|
| Wikipedia | encyclopedic background | on |
| arXiv | research papers | on |
| OpenAlex | paper abstracts across all fields | on |
| Stack Exchange | math, cs, stats and Stack Overflow answers (accepted or score ≥ 3 only) | on |
| cp-algorithms | competitive-programming algorithms, searched through the site's own index, fetched with exact math | on |
| Semantic Scholar | highly cited papers (keyless access is rate-limited) | off |
| OEIS | integer sequences: terms, formulas, comments | off |
| your vault | your notes and saved articles | on |

Turn sources on or off in the plugin settings, with `--sources` on the CLI, or in `config.py`.

### Obsidian

```bash
.venv\Scripts\python scripts/setup_obsidian.py
```

This creates `Desktop\Michael Vault` (or pass another vault path), installs and enables the plugin, adds a welcome note and a sample note, and registers the vault with Obsidian. Re-run it after rebuilding the plugin (`cd obsidian-michael && npm run build`).

In Obsidian: the first time, click **Turn on community plugins** when asked. Then click the ribbon icon or run **Michael: Research a question** (`Ctrl+P`). The plugin starts `michael serve` by itself, sends its vault as a source, accepts extra URLs, shows progress in the status bar and opens the finished note from `Michael/`. **Michael: Add an article** (second ribbon icon) does the article flow above inside the vault.

## Evaluation (resume numbers)

```bash
.venv\Scripts\python eval\prepare_scifact.py
```

```bash
.venv\Scripts\python eval\run_eval.py verifier
```

```bash
.venv\Scripts\python eval\run_eval.py rerank
```

```bash
.venv\Scripts\python eval\run_eval.py citations
```

Reports are saved in `eval/reports/`. `citations` uses the right/wrong labels you give in the dashboard.

## Tests

```bash
.venv\Scripts\python -m pytest -q
```

## Configuration

All settings live in `backend/michael/config.py` and can be overridden with `MICHAEL_*` environment variables, e.g. `MICHAEL_LLM=qwen2.5:7b`, `MICHAEL_VAULT`, `MICHAEL_OLLAMA_URL`. The default thresholds are entailment ≥ 0.70 for SUPPORTED and ≥ 0.40 for PARTIAL.

## Honest limits

- The verifier proves that a quote supports a sentence, not that the source is true.
- Sentence-level checking struggles with conclusions that combine several passages; those show as PARTIAL.
- On a CPU laptop a full run takes a few minutes with `qwen2.5:3b`.
- PDFs that are not on arXiv keep their text but not their math; a PDF-to-LaTeX model (Marker) is the planned next step.
