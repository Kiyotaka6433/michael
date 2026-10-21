# Michael - evidence-locked research agent for Obsidian

[![ci](https://github.com/Kiyotaka6433/michael/actions/workflows/ci.yml/badge.svg)](https://github.com/Kiyotaka6433/michael/actions/workflows/ci.yml)

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
| `pravuil.py` | Pravuil | keeper of the heavenly records | adds articles to the vault and writes verified key points and topic notes |
| `zachriel.py` | Zachriel | angel of memory | flashcards from verified sentences |

## Setup (Windows, CPU only)

**One command** (installs what's missing after asking, builds the plugin, sets up the vault, runs the tests; safe to re-run):

```bash
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Or step by step:

1. Install Ollama and pull the writing model:

```bash
winget install Ollama.Ollama
```

```bash
ollama pull qwen2.5:7b
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

```bash
.venv\Scripts\python scripts/build_library.py topics
```

`fetch` saves every article verbatim with exact math (seconds each), `hubs` writes `Home.md` and one hub note per subject (topics → overview → articles → key points) and adds a "Related" section to each article (nearest articles by embedding, across subjects), `topics` writes one verified overview per topic from all of its articles, and `keypoints` writes a verified key-points note per article (minutes each; resumable, progress in `library/state.json`).

Every topic and key-points note also gets a flashcard deck in `<Subject>/Flashcards/` for the Obsidian **Spaced Repetition** plugin (`Question::Answer`, tag `#flashcards/<subject>`). Only sentences the verifier marked SUPPORTED become cards, and the answer is that verified sentence unchanged, with a link to its quote (`zachriel.py`).

The saved articles are a source for every later question; Michael's own notes (answers, key points, topic notes, hubs, flashcards) never are, so it cannot cite itself.

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

## Results (measured on this laptop: Ryzen 5 7520U, CPU only)

**Verifier benchmark** (SciFact dev, 450 claim/evidence pairs, `eval/compare_verifiers.py`):

| Verifier | ms / pair | Precision @0.70 | Recall @0.70 |
|---|---|---|---|
| DeBERTa-v3-base (mnli-fever-anli) | 326 | 95.4% | 28.7% |
| **DeBERTa-v3-large (…-ling-wanli), used** | 1013 | **98.9%** | **40.7%** |
| MiniCheck-DeBERTa-v3-Large | 1174 | 97.8% | 20.4% |
| deberta-v3-base-zeroshot-v2.0 | 337 | 95.6% | 30.1% |
| deberta-small-long-nli | 154 | 93.2% | 25.5% |

**Michael's own notes** (gold set: 247 sentences from generated notes, labelled `claude-audit`, i.e. AI-audited, not human-labelled; `eval/gold_report.py`):

| | Before claim-driven retrieval (157) | After (90) |
|---|---|---|
| Verified sentences that are right (strict) | 91.3% | **92.7%** |
| ... right or only imprecise | 99.0% | **100%** |
| Wrong sentences left in notes | 1 | **0** |
| Drafted sentences kept as verified (yield) | 66.2% | **91.1%** |
| Drafted sentences removed | 26% | **7%** |

**Maths-aware checking** (`host/ophaniel.py`: LaTeX → SymPy, equivalence by evaluation at random points, big-O by growth rate, numbers must appear in the evidence). Pairs are real sentences from the library, each with a copy that has one quantity changed:

| Benchmark | Rule | True sentences accepted | Wrong sentences accepted |
|---|---|---|---|
| Changed formula or number, same notation (400 pairs, `eval/math_benchmark.py`) | NLI | 91.0% | 0.5% (formulas: 2.0%) |
| | NLI + maths | 91.0% | **0.2%** (formulas: **1.0%**) |
| Same formula in a different form, e.g. expanded or factored (150 pairs, `eval/math_equivalence_benchmark.py`) | NLI | 56.0% | 2.0% |
| | NLI + maths | **69.3%** | **0%** |

In the second benchmark, a PARTIAL sentence is upgraded to verified only when every formula in it is proven equivalent to the evidence's (`MICHAEL_MATH_UPGRADE`).

**Baseline: the same drafts with and without the verifier** (`eval/baseline_drafts.py`, `eval/baseline_controlled.py`; 14 notes, labels `claude-audit`):

| Writer | Without verifier: correct / partly / wrong | With verifier (only SUPPORTED shown) | Correct drafts dropped |
|---|---|---|---|
| qwen2.5:7b (86 drafts) | 90.7% / 9.3% / 0% | **95.2% / 4.8% / 0%** | 19 of 78 |
| qwen2.5:3b (112 drafts) | 90.2% / 8.0% / 1.8% | **98.5% / 1.5% / 0%** | 36 of 101 |

The verifier removed both wrong 3B sentences (2 of 2: a wrong Dijkstra running time and a misattributed author contribution) and most of the imprecise ones. The cost is recall: about a third of correct drafts are dropped before repair. In the full pipeline, claim-driven retrieval re-cites most of them (yield 91%).

**Recall without losing precision** (`eval/gate.py`: the 198 baseline drafts re-verified against their note's full evidence, no LLM repair; also run as the `pytest -m eval` regression gate):

| Verifier setting | Correct drafts lost | Strict precision (drafts / gold) | Wrong accepted |
|---|---|---|---|
| Before (17 Oct) | 33.5% (60/179) | 96.7% / 91.8% | 0 |
| + compound sentences proven part by part | 32.4% | 96.8% | 0 |
| + quotes judged with their source title as context, but only when the quote shares the sentence's wording (overlap ≥ 70) | 26.3% | **97.1% / 92.6%** | 0 |
| + claim-driven retrieval: failing sentences search all source files (the full pipeline) | 17.3% (31/179) | 95.5% / 92.1% | 0 |
| + 6 passages per failing sentence in the search (was 3) | 16.8% | 95.5% / 92.1% | 0 |
| + a failing sentence judged against its two closest separate quotes joined, at the paragraph bar (0.90) | 15.1% (27/179) | 95.0% / 92.1% | 0 |
| + the parts of a split compound sentence also get the title-context retry | **14.0%** (25/179) | **95.1% / 92.1%** | **0** |

(At 0.70 the two-quote retry reached 12.8%, but it let sentences through on context the single-quote rule only accepts at 0.90; an existing unit test caught it, so it uses 0.90.)

The quote is often worded with a pronoun ("In both contexts, *it* refers to…"), so the NLI model couldn't tell what it was about. Sentences that pass only with this title context are marked as such in their footnote. Without the overlap floor, the title alone let a true sentence through on an unrelated quote; this was caught in the Obsidian trust panel and has a regression test.

**Negative results, kept off:**
- **Near-verbatim relaxation** (accept 0.5–0.7 when the sentence copies its quote): no gain on the drafts.
- **Contradiction flags between sources:** all 3 flags raised were false alarms.
- **Two-stage verifier** (a small NLI model screens, the large one judges): at the setting that loses no accepted sentences, the large model still judged 90% of pairs, so it would have been slower overall.

**Topic overviews rewritten from the new trusted sources** (`build_library.py retopics`): 20 of 23 rewrites beat the old note and replaced it, and the 3 that didn't were kept. Median verified sentences per overview went from 4 to 6, e.g. *Core data structures* 1 → 11 and *Divisibility and the GCD* 6 → 13. Old versions are kept in `<Subject>/Archive/`.

**Where a note's time goes** (`eval/profile_note.py`, one key-points note, CPU only, with Ollama's own timings):

| Stage | Share | Notes |
|---|---|---|
| Writer (qwen2.5:7b) | 60–75% | half reading the evidence prompt (~1,700 tokens at 27 tok/s), half generating (~6 tok/s) |
| Reranker | 10–15% | bge-reranker-base over 20–30 candidates |
| Verifier | 10–25% | mostly the recall retries on sentences that fail at first |

Tried and **not adopted**, each measured:
- **Two-stage verifier:** the large model still judged 90% of pairs.
- **int8 verifier:** 492 of 498 accepts flipped.
- **Closest-window-first:** 3% fewer pairs.
- **qwen2.5:3b writer:** drafts about 1.6× faster and more verified sentences, but no faster end to end (more repairs).

**Speed and fidelity**
- Key-points note for one paper: 29 min → 8.5 min (3.4×), then ~5–6 min with qwen2.5:7b and batching. Fixes: float32 instead of float16 on CPU (verifier 9.3× faster), all CPU threads for Ollama (1.7×), batched NLI, result caches.
- Library: 184 articles saved from Wikipedia, cp-algorithms, scikit-learn, d2l.ai and arXiv; **20,335 / 20,438 formulas (99.5%) render** (arXiv papers from their LaTeX source via pandoc, others from MathJax/KaTeX/LaTeXML alt-text, every formula checked with MathJax).
- Vault graph: ~220 notes, ~2,100 links; 26 verified topic overviews; flashcards from verified sentences only.
- Citation re-check: 85/86 quotes still match their source word for word.

## Evaluation (how to reproduce)

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
- On a CPU laptop a note takes several minutes with `qwen2.5:7b` (set `MICHAEL_LLM=qwen2.5:3b` for about 2x faster, plainer writing).
- PDFs that are not on arXiv keep their text but not their math; a PDF-to-LaTeX model (Marker) is the planned next step.

### Send any web page to Michael

Run **Michael: Copy the 'Send page to Michael' browser bookmarklet** in Obsidian, create a browser bookmark and paste it as the URL. Clicking it on any page opens `obsidian://michael-add?url=...`, which saves the page (with exact math) and writes verified key points. `obsidian://michael-ask?q=...` starts a research question the same way, so a web page or the companion web app can link straight into Obsidian.

Other commands: **Re-index the vault**, **Check that every citation still matches its source** (writes `Michael/Citation check.md`). The backend also runs these every night at 02:00 (`MICHAEL_NIGHTLY_HOUR`), plus key points for newly added articles.

### Chrome / Edge extension: file what you read

`browser-extension/` suggests the right library topic for the article you are reading and adds its **link** (name + URL) to that topic with one click.

1. Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → choose `browser-extension/`.
2. Nothing to paste: the backend writes `browser-extension/local-token.json` (git-ignored) and the extension picks it up. (Fallback: **Michael: Copy extension token** in Obsidian, then paste it in the extension's Settings.)
3. Read an article for ~20 s (or scroll a third of it): a small card asks *"Add this page to Number Theory › Modular arithmetic?"* with **Add / Other topic / Not now / Never on this site**.

It never appears on mail, search, social, shopping, banking or video sites, or on pages that are not articles. **Alt+Shift+M** asks about any page right away; a green ✓ on the toolbar icon means the page is already in your library. Single-page sites (Medium, docs) are followed as you navigate, and each page is classified once per browser session. A page that is already in the vault says so instead. **Add** writes `<Subject>/Links/<Title>.md` (`michael: link`, never used as evidence) and lists it under the topic's *Reading list* in the hub; links get a lighter shade of their subject colour in the graph.

How it picks the topic (`host/raziel.py`): the page's title and opening text are embedded (bge-small) and compared with each topic's centroid, the mean embedding of its saved articles. Confidence is a softmax over those similarities; below 0.35 the link goes to the subject's *Inbox*. No LLM, about 100 ms. Page text only goes to the local backend (`127.0.0.1`), which requires the token for every request.
