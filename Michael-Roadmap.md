# Michael - Roadmap to the best version

**Goal:** the most trustworthy free research assistant for Obsidian. Every sentence it writes is provably backed by a source, it's fast enough to use daily, and it's simple enough that a classmate can install it in 10 minutes.

**Resume domain:** Applied AI / ML engineering → LLM applications, RAG, LLM evaluation and hallucination reduction.

---

## Where we are (17 Oct 2026)

| Area | Status |
|---|---|
| Pipeline | plan → 7 sources + vault → hybrid search → rerank → write (qwen2.5:7b) → verify (DeBERTa-large NLI) → repair → Obsidian note |
| Accuracy | verifier 99% precision / 41% recall on SciFact at 0.70; paragraph context with a stricter 0.90 bar |
| Speed | key points 29 min → 8.5 min (float32 fix, threads, batching) |
| Library | 184 articles, 20,438 formulas (99.5% render), 26 topics, ~2,000 links, canvas maps, flashcards |
| Ship | GitHub repo, 26 offline tests, README |
| Running | topic notes + key points + flashcards batch (qwen2.5:7b) |

---

## Phase 1: Prove it (accuracy you can quote) *(3-4 days)*

The resume rests on numbers, so this comes first.

1. **Gold evaluation set (`eval/gold/`)**: ~150 sentences from real Michael notes, each labelled *correct / wrong / partially correct*, with a reason. Claude does the labelling and the dataset marks the labels as "AI-audited". You check a random 15, and we report how often you agree with the labels.
2. **Metrics report (`eval/report.md`, generated)**:
   - **Citation precision:** of the sentences marked verified, the share that are correct. Target ≥ 95%.
   - **Yield:** verified sentences ÷ drafted sentences. Target ≥ 70%; Primes is at 50% today.
   - **Over-removal:** true sentences that got removed. Target ≤ 15%.
   - Speed per note, warm and cold.
3. **Regression gate**: `pytest -m eval` re-scores the gold set. Any change that lowers precision fails the check.
4. **Yield fixes** (directly raise usefulness):
   - Writer prompt with per-subject examples (a definition, a theorem, an algorithm with its complexity).
   - Give the writer the *quote windows* rather than whole passages, so sentences start close to the source wording.
   - **Decontextualise** sentences before checking: replace "it" or "this algorithm" with the subject (one cheap LLM call). This fixes many false rejections.
5. **Contradiction flag**: if two sources disagree (high contradiction score), say so in the note instead of silently choosing one.

**Done when:** the report shows ≥ 95% precision and ≥ 70% yield on the gold set, and the CI gate is green.

---

## Phase 2: Fast enough for daily use *(2-3 days)*

Target: a question answered in about 2 minutes warm, with the first sentences visible within 60 seconds.

1. **Verifier cascade**: the small NLI model (154 ms per pair) screens every candidate, and the large model (99% precision) only judges the close calls. Expected 2-3× faster checking with the same precision. Measure it on the gold set before switching.
2. **ONNX Runtime** (float32) for the reranker and verifier: usually 1.5-2× faster on CPU with identical outputs. Verify that outputs match to within 1e-4.
3. **Streaming answers**: write and check sentence by sentence, so the note fills in live in Obsidian.
4. **Two-model writing**: qwen2.5:3b drafts, qwen2.5:7b only repairs. Measure whether quality holds.
5. **Warm cache everywhere**: precomputed embeddings for the whole library (already cached), plus a reranker score cache per (question, chunk).
6. **Preset modes**: *Fast* (3b, base verifier), *Balanced* (default), *Thorough* (7b, large verifier, 2 repair rounds).

**Done when:** a Balanced question takes ≤ 2.5 min warm (measured), and precision on the gold set is unchanged.

---

## Phase 2B: Data and backend *(4-6 days)*

**Local-first:** the vault's Markdown files are the source of truth; the database is a derived index plus app state; a file watcher keeps them in sync. The backend never needs Obsidian to be open.

1. **Vault index** (SQLite): notes, chunks, links, claims, verdicts, flashcards. Full-text search (FTS5) + vector search, combined with RRF. Incremental: only changed files are re-indexed. Rebuildable from the vault at any time.
2. **Caches** for LLM responses and NLI scores, keyed by input hash. Repeat runs become near-instant.
3. **Persistent job queue** (SQLite): survives restarts, with priority, cancel and retry. Research, add-article and library builds all become jobs with live progress.
4. **Vault watcher** (watchfiles, with a delay for OneDrive): re-indexes edits. The file always wins.
5. **Scheduler** (APScheduler): nightly key points for new articles, quote re-checks (provenance), topic-watch digests.
6. **Provenance**: a content hash per saved article; nightly re-check that every quote still exists; changes are flagged.
7. **Learning data**: SM-2 state mirrored from the Spaced Repetition comments, a review log, retention stats.
8. **Feedback loop**: labels drive threshold calibration and per-source reliability.
9. **API v1**: versioned routes, pagination, consistent errors, one event stream, auto-generated TypeScript client, and an access token between the apps and the backend.

## Phase 3B: Companion web app, linked with Obsidian *(6-9 days)*

1. **Next.js web app** on the same backend: library browser, search, KaTeX maths, notes with hover quotes, interactive graph (Cytoscape), flashcard review (SM-2, PWA for phone, writes the same `<!--SR:...-->` comments), live research page (streaming).
2. **Obsidian ↔ web links**: "Open in Obsidian" buttons (`obsidian://open`), plugin protocol handler `obsidian://michael-add?url=` with a bookmarklet, "Open this note on the web" command, and the web app inside an Obsidian side panel.
3. **Quartz public site** (GitHub Pages, free): read-only Sources / Topics / Key points with graph and maths.
4. **Docker Compose** (api, web, ollama), Playwright + Vitest tests, CI/CD, a public read-only demo on Hugging Face Spaces.

---

## Phase 3: Extremely usable in Obsidian *(4-5 days)*

1. **Michael side panel** (a proper Obsidian view, not just commands):
   - Ask box, mode picker and source toggles.
   - Live progress per stage, with the sentences appearing as they're verified.
   - History of past runs; click one to open its note.
   - A "Library" tab with articles, topics, flashcards due, and buttons to build or refresh.
2. **Inline trust UI**:
   - Hover a sentence to see its quote, the source and the score.
   - Colour gutter: green = verified, yellow = partial.
   - "Re-verify this note" after you edit it.
3. **One-click actions** (command palette and right-click menu):
   - *Explain selection*, *Verify selection*, *Add this link/PDF*.
   - *Make flashcards from this note*.
   - *Find what my notes say about X*.
4. **Capture from the browser**: an `obsidian://michael-add?url=...` link handler and a browser bookmarklet, so one click on any page adds it to the library.
5. **First-run setup wizard**: checks Ollama, the models, pandoc and Node, downloads what's missing with progress, and gives clear fixes for each error.
6. **Friendly failures**: no stack traces, and every error says what to do next.

**Done when:** a new user can go from install to first verified note without opening a terminal.

---

## Phase 4: Study superpowers *(4-6 days)*

1. **Study mode for a topic**: overview, then flashcards, then a 5-question quiz with answers checked against the sources, then the weak spots highlighted.
2. **Coverage map**: for each topic, which key concepts have verified notes and which are missing. Shown as a canvas with gaps highlighted.
3. **"What do my notes say?"**: answers only from your vault, citing your own notes.
4. **Note checker**: flags sentences in *your* notes that contradict the library sources.
5. **Watch a topic**: a daily arXiv / cp-algorithms digest for chosen topics, auto-added and summarised overnight.
6. **More sources**:
   - **Marker** for maths in non-arXiv PDFs.
   - Web search (DuckDuckGo) restricted to a trusted-site list.
   - YouTube transcripts for lectures.
   - Semantic Scholar with your API key.

**Done when:** you can revise one subject entirely inside the vault (topic → cards → quiz) for an exam.

---

## Phase 5: Package and ship *(2-3 days)*

1. **One-command install**: `setup.ps1`, which creates the venv, installs pinned requirements, pulls the models, installs pandoc and Node tools, builds the plugin and sets up the vault.
2. **GitHub Actions CI**: lint (ruff), offline tests and the plugin build on every push. Add a badge to the README.
3. **Releases**: a tagged version with the plugin zip attached, and a changelog.
4. **Obsidian community plugin submission**: manifest, release, and a PR to `obsidianmd/obsidian-releases`.
5. **Docs**: README quick-start, architecture diagram, configuration, FAQ and troubleshooting.

**Done when:** a fresh Windows machine reaches its first note by following the README alone.

---

## Phase 6: Showcase *(1-2 days)*

1. **README "Results" section** with the real numbers: the precision/yield table, speed before and after, verifier benchmark chart, formula rate, and library size.
2. **Screenshots and GIF**: the graph web, a canvas map, a verified note with a hover quote, and a flashcard review.
3. **2-minute demo video**: ask a question, watch the live verification, open the quote, review cards.
4. **Write-up / blog post**: "Making a 3B model trustworthy: evidence-locked notes on a laptop CPU", covering the float16 finding, the verifier benchmark, paragraph context, and the precision/yield trade-off.
5. **Resume bullets** (template; fill in final numbers):
   - Built **Michael**, an evidence-locked research agent for Obsidian (Python, FastAPI, TypeScript, Next.js) that verifies every generated sentence against an exact source quote with an independent NLI model: **X% citation precision** on an audited gold set.
   - Benchmarked **5 NLI verifiers** on SciFact and found a float16-on-CPU slowdown; cut note generation time from **29 → N min** with profiling, batching and a verifier cascade.
   - Built a library pipeline that saved **184 articles with 99.5% LaTeX fidelity** (arXiv source via pandoc, MathJax validation), auto-linked into a **~2,000-edge knowledge graph** with verified topic notes and spaced-repetition flashcards.

---

## Order of work (about 5 weeks)

1. **Week 1:** Phase 1 (gold set, metrics, yield fixes) + Phase 2B.1-2 (vault index, search, caches).
2. **Week 2:** Phase 2B.3-6 (job queue, watcher, scheduler, provenance) + Phase 3B.2 (Obsidian ↔ web links) + Phase 2 (cascade, streaming).
3. **Weeks 3-4:** Phase 3B.1 (web app: library, then flashcards, then live research) + 3B.3 (Quartz) + Phase 3 (side panel, hover quotes, setup wizard).
4. **Week 5:** Phase 5 (installer, CI, release) + 3B.4 (Docker, public demo) + Phase 6 (showcase).
5. **Afterwards:** Phase 4 depth features.

## What I need from you

- **Spot-check 15 labels** from the gold set (about 10 minutes).
- **A Semantic Scholar API key** when convenient.
- **Use it for real** for a week on DSA, number theory and ML coursework, and tell me what annoys you. That feedback outweighs any feature on this list.
- **Record the demo video** at the end (I'll write the script).
