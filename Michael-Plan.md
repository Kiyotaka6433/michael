# Michael - Evidence-Locked Research Agent for Obsidian

Project plan tailored to: Ryzen 5 7520U, 16 GB RAM, integrated AMD graphics. There is no NVIDIA GPU, so every model runs on the CPU and the plan uses small, fast models. Python, Node and Git are already installed; Ollama is not yet.

## 1. What it does

```
You ask: "How does LACP differ from PAgP?"
  1. Plan          → split the question into 3-5 search queries
  2. Gather        → free sources: Wikipedia, arXiv, OpenAlex, Semantic Scholar, any URL or PDF you add,
                     AND your own Obsidian vault
  3. Chunk + index → split into passages, embed them, store them with their source and position (cached)
  4. Search        → hybrid BM25 + embeddings returns the top 30 candidates
  5. Rerank        → a cross-encoder rescores them and keeps the best 8 as evidence
  6. Draft         → the LLM writes an answer where every sentence cites a passage ID [p12]
  7. Verify        → for each sentence: find the exact supporting quote in the cited passage,
                     then a separate NLI model decides: SUPPORTED / PARTIAL / UNSUPPORTED
  8. Repair        → rewrite or delete unsupported sentences, re-verify (at most 2 rounds)
  9. Publish       → an Obsidian note: every sentence links to a footnote containing the exact quote and URL
                     (or a [[Note#Heading]] link when the evidence comes from your vault),
                     plus a trust panel: "14/16 sentences verified, 2 flagged"
```

Michael is a RAG (retrieval-augmented generation) system with two upgrades built in from the start:

- **Reranker:** search finds 30 candidate passages quickly; a cross-encoder then reads each question–passage pair together and keeps the best 8. Better evidence in means fewer weak citations out.
- **Your vault as a source:** your own notes are indexed next to the public sources, so answers build on what you already know and cite it as `[[Note#Heading]]`.

The key design rule is that **the model that writes is never the model that grades**. A drafting LLM marking its own homework proves nothing. An independent NLI classifier checking each sentence against its quote is what makes the trust score defensible.

## 2. Architecture

```
┌──────────────────────────┐        ┌───────────────────────────────────────┐
│ Obsidian plugin (TS)     │  HTTP  │ FastAPI backend (Python)              │
│ - "Ask" command / panel  │◄──────►│  /research  (job)  /status  /verify   │
│ - renders note+footnotes │  SSE   │                                        │
└──────────────────────────┘        │  Orchestrator (state machine)          │
┌──────────────────────────┐        │   ├─ Planner      (LLM)               │
│ Web dashboard (Next.js)  │◄──────►│   ├─ Retrievers   (Wikipedia, arXiv,  │
│ - run history, metrics   │        │   │               OpenAlex, URL/PDF)  │
│ - claim-by-claim review  │        │   ├─ Vault indexer (your .md notes)   │
│                          │        │   ├─ Chunker + Embedder (bge-small)   │
└──────────────────────────┘        │   ├─ Hybrid search (BM25 + vectors)   │
                                     │   ├─ Reranker (bge-reranker-base)     │
                                     │   ├─ Writer       (LLM, cites [pN])   │
                                     │   ├─ Quote locator (fuzzy span match) │
                                     │   ├─ Verifier     (DeBERTa NLI)       │
                                     │   └─ Repairer     (LLM, max 2 loops)  │
                                     │  SQLite: sources, chunks, claims,     │
                                     │          verdicts, runs  + sqlite-vec  │
                                     └──────────────┬────────────────────────┘
                                                    │
                                      Ollama (local LLM server, CPU)
```

### Components and why each one exists

| Component | Choice | Why |
|---|---|---|
| LLM (planning, writing, repair) | Ollama with **qwen2.5:3b** by default; qwen2.5:7b for quality runs | A 3B model runs at roughly 10–15 tokens/s on this CPU, 7B at roughly 4–6. Optional switch to Groq's free tier for fast demos |
| Embeddings | `BAAI/bge-small-en-v1.5` (sentence-transformers) | 33M parameters, fast on CPU, good retrieval quality |
| Keyword search | `rank-bm25` | Exact terms such as "LACP" or "802.3ad" that embeddings can miss |
| **Reranker** | `BAAI/bge-reranker-base` via `sentence-transformers` `CrossEncoder` | Rescores the top 30 candidates and keeps the best 8; usually the biggest single gain in citation precision; about 2–4 s per question on CPU |
| **Vault source** | Plain Python (`pathlib` + heading-based splitting), `watchfiles` for changes | Your notes become citable evidence; re-indexes only files whose hash changed |
| **Cache** | Content hashes in SQLite | Sources and embeddings are never fetched or computed twice |
| Verifier | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | A model trained specifically to judge whether a passage supports, contradicts or is neutral to a statement; about 0.1 s per sentence on CPU |
| Quote locator | `rapidfuzz` + sentence splitting (`pysbd`) | Finds the exact supporting span inside the cited passage |
| Storage | SQLite + `sqlite-vec` | One file, nothing to run, free |
| Sources | Wikipedia REST API, arXiv API, OpenAlex, Semantic Scholar | All free; OpenAlex needs no key |
| Web pages | `trafilatura` | Extracts the main text from a page |
| PDF | `pymupdf` | Fast, keeps page numbers for citations |
| Backend | FastAPI + `uvicorn`, server-sent events for progress | Async; streams each stage to the UI |
| Obsidian plugin | TypeScript, official sample-plugin template | Uses Obsidian's plugin API |
| Dashboard | Next.js + Tailwind + Recharts | Run history, metrics, claim-by-claim review |
| Evaluation | `pytest` + custom scripts | Measured numbers for the resume |

### Data model (SQLite)

```
sources(id, url_or_path, title, kind, fetched_at, hash)      -- kind: wikipedia | arxiv | openalex | web | pdf | vault
chunks(id, source_id, text, start_char, end_char, page, heading, embedding, content_hash)
runs(id, question, model, started_at, finished_at, status)
claims(id, run_id, sentence, cited_chunk_ids, position)
verdicts(id, claim_id, quote, quote_start, quote_end, label, entail_prob, round)
```

Storing every character offset means any sentence can be traced back to the exact text it came from. That traceability is the core of the "evidence-locked" claim.

## 3. What to install (Windows)

```bash
winget install Ollama.Ollama
```

```bash
winget install astral-sh.uv
```

```bash
ollama pull qwen2.5:3b
```

```bash
ollama pull qwen2.5:7b
```

Use Python **3.12** for this project rather than 3.13; some ML packages are more reliable on 3.12. `uv` manages it for you:

```bash
uv init michael --python 3.12
```

```bash
cd michael
```

```bash
uv add fastapi uvicorn[standard] httpx pydantic sqlite-vec rank-bm25 sentence-transformers transformers torch rapidfuzz pysbd trafilatura pymupdf arxiv wikipedia-api sse-starlette watchfiles
```

```bash
uv add --dev pytest ruff datasets
```

Frontend (Node 24 is already installed):

```bash
npx create-next-app@latest dashboard --ts --tailwind --app
```

```bash
git clone https://github.com/obsidianmd/obsidian-sample-plugin obsidian-michael
```

Also install Obsidian (free) with a test vault.

The reranker (`BAAI/bge-reranker-base`, about 1.1 GB) downloads automatically on first use.

- **Disk:** about 10 GB in total (both LLMs ≈ 6.7 GB, torch ≈ 1 GB, reranker ≈ 1.1 GB, other models ≈ 0.5 GB).
- **Cost:** ₹0.

## 4. Repository layout

```
michael/
├── backend/
│   ├── app.py                # FastAPI routes, SSE progress
│   ├── pipeline/
│   │   ├── planner.py        # question → search queries
│   │   ├── retrieve/         # wikipedia.py, arxiv.py, openalex.py, web.py, pdf.py, vault.py
│   │   ├── index.py          # chunking, embeddings, hybrid search, cache
│   │   ├── rerank.py         # cross-encoder: top 30 → best 8
│   │   ├── writer.py         # draft with [pN] citations, strict JSON output
│   │   ├── locate.py         # exact quote span inside the cited chunk
│   │   ├── verify.py         # NLI verdicts + thresholds
│   │   ├── repair.py         # fix or drop unsupported sentences
│   │   └── export.py         # Obsidian Markdown with footnotes + trust panel
│   ├── db.py
│   └── config.py             # model names, thresholds, source toggles, vault path
├── eval/
│   ├── datasets/             # SciFact, FEVER sample, your own labelled set
│   ├── run_eval.py           # metrics below
│   └── reports/
├── obsidian-michael/         # TypeScript plugin
├── dashboard/                # Next.js
└── README.md                 # architecture diagram, metrics table, demo GIF
```

## 5. Week-by-week plan

| Week | Build | Done when |
|---|---|---|
| 1 | Retrievers (Wikipedia, arXiv, OpenAlex, **your vault**), chunking, embeddings with cache, hybrid search, **reranker**, SQLite schema | `search("LACP vs PAgP")` returns the best 8 reranked passages, including your own notes, with their sources |
| 2 | Writer with forced `[pN]` citations (strict JSON), quote locator | Every draft sentence has a cited passage and an exact quote span |
| 3 | NLI verifier, thresholds, repair loop; **evaluation harness** | Verifier scores on SciFact and your labelled set |
| 4 | FastAPI with progress streaming; Obsidian plugin (command → note with footnotes and trust panel) | One-click "research this" inside Obsidian |
| 5 | Next.js dashboard: run history, claim-by-claim review, mark verdicts right/wrong | Your corrections are saved as new labelled data |
| 6 | Ablations and final evaluation, README with metrics, a 90-second demo video | Resume numbers measured and reproducible |

Start each week with the evaluation script, not the UI. The numbers are the product.

## 6. Evaluation: the part that makes it impressive

| Metric | What it measures | Data |
|---|---|---|
| **Citation precision** | Of the sentences marked verified, how many truly are | ~150 sentences you label yourself from real runs |
| **Citation recall** | Of the truly supported sentences, how many the system keeps | Same set |
| **Unsupported-claim rate**, before vs after verification | How much the verifier reduces hallucination | Your runs |
| **Verifier accuracy / F1** | How good the NLI judge is | **SciFact** (scientific claims labelled supported/refuted) and a FEVER sample, both free on Hugging Face |
| **Answer coverage** | Whether verification deletes too much | Fraction of sentences kept |
| **Latency per stage** | Practicality on a CPU laptop | Logged per run |

**Ablations** (comparisons that show which design choices matter):

1. No verifier vs NLI verifier vs NLI + repair.
2. Embeddings only vs hybrid BM25 + embeddings vs hybrid + reranker.
3. Public sources only vs public sources + your vault.
4. 3B vs 7B writer.

Report them as a table in the README. A table of comparisons is what makes engineers take a project seriously.

## 7. How useful will it actually be?

**Genuinely useful for:**

- Researching assignments and reports. Every claim arrives with its quote and source, which also helps academic integrity: you can see exactly where each fact came from.
- Viva and exam preparation: "explain X with sources" gives you a revision note you can trust.
- Literature surveys for an ML project: arXiv and OpenAlex coverage is strong.
- Your own fact-checking: paste a URL or PDF and ask it to verify a claim.

**Limitations to expect:**

- **Speed:** 1–3 minutes per question on this CPU with the 3B model, longer with 7B. Fine for research, not for chat.
- **Source coverage:** free academic and encyclopedic sources only. No paywalled papers, and general web search is limited without a paid API. You can add any URL or PDF yourself.
- **What the verifier proves:** it checks that the quote supports the sentence, not that the source itself is correct. A wrong source that is quoted accurately will still pass. Say this upfront; interviewers respect it.
- **Hard cases:** reasoning across several passages ("A and B, therefore C") is hard for sentence-level checks. Mark such sentences "partial" rather than claiming support.

Overall: a strong personal tool for research and revision, and a clear, honest demonstration of how to make LLM output trustworthy, which is one of the most in-demand skills right now.

## 8. Resume use

**Project title:** Michael, an evidence-locked research agent for Obsidian (Python, FastAPI, Ollama, DeBERTa-NLI, SQLite-vec, TypeScript, Next.js).

Bullet templates (fill in your measured numbers):

- "Built a local-first, retrieval-augmented research agent that ties every generated sentence to an exact source quote and verifies it with an independent NLI model, cutting unsupported claims from **X% to Y%** on 150 labelled sentences."
- "Implemented hybrid BM25 + dense retrieval with cross-encoder reranking over arXiv, OpenAlex, Wikipedia and the user's own Obsidian vault; reranking raised citation precision from **__ to __**."
- "Validated the verifier at **F1 = __ on SciFact**; added a two-round repair loop that kept **__%** of sentences while removing unsupported ones."
- "Shipped an Obsidian plugin and a Next.js review dashboard that turn user corrections into new labelled evaluation data; runs at ₹0 cost on a CPU-only laptop."

**Interview talking points:**

- Why the writer and the verifier must be separate models.
- Thresholds and the precision/recall trade-off in verification.
- Hybrid vs dense retrieval, and why a cross-encoder reranker is more accurate but too slow to run on every passage (hence top 30 → best 8).
- Running models on a CPU with quantised LLMs.
- Why the verifier proves attribution, not truth.

## 9. First step

1. Install Ollama and `uv` (commands above).
2. Pull `qwen2.5:3b`.
3. Create the project.
4. Write `retrieve/wikipedia.py`, `retrieve/vault.py` and `index.py`, and get one question returning ranked passages from Wikipedia and your notes.
5. Add `rerank.py` and compare the top 8 before and after reranking on 5 questions; that is your first measured result.

### Reranker in a few lines

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("BAAI/bge-reranker-base")   # loads once at startup

def rerank(question, candidates, keep=8):
    scores = reranker.predict([(question, c.text) for c in candidates])
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [c for c, _ in ranked[:keep]]
```

### Vault indexing idea

```python
from pathlib import Path
import hashlib, re

def vault_chunks(vault_dir):
    for md in Path(vault_dir).rglob("*.md"):
        text = md.read_text(encoding="utf8")
        digest = hashlib.sha256(text.encode()).hexdigest()   # skip if unchanged since last run
        for part in re.split(r"(?m)^(?=#{1,3} )", text):      # one chunk per heading section
            heading = part.splitlines()[0].lstrip("# ").strip() if part.startswith("#") else md.stem
            if part.strip():
                yield {"path": str(md), "heading": heading, "text": part, "hash": digest,
                       "link": f"[[{md.stem}#{heading}]]"}
```
