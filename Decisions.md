# Decisions log

What was done each hour, the choices made, and why. Newest first. Times are local (IST).

---

## 2026-10-17 · 14:00-15:00
**Done**
- **All 26 topic overviews finished: 120/134 sentences verified, 100 flashcards.** The batch moved on to key points for 84 papers and tutorial pages (overnight).
- **Claim-driven retrieval:** before a sentence is removed, the whole collected pool is searched with that sentence, and the sentence is kept if another passage proves it. The previously failed topic "Unsupervised learning" came out 5/5.
- **Chrome extension live in your browser:** connects without copy-paste (git-ignored `local-token.json`), link titles cleaned ("Bloom filter", not "Bloom filter - Wikipedia"), topic vectors precomputed at start-up so the first suggestion is instant.
- **Web app (Phase 3B):**
  - `/library`: subjects → topics → overviews, articles, key points, reading lists.
  - `/note`: renders a note with exact math; all 138 Transformer formulas render with 0 errors. Links between notes work, backlinks show, and an "Open in Obsidian" button is on every page.
  - `/search`: full-text and meaning search.
  - `/flashcards`: reviews shared with the Obsidian Spaced Repetition plugin.
  - `/graph`: 221 notes and 2,105 links in the Obsidian colours (Cytoscape); hover to focus, click to open.
- Key points started: **6/84 done so far, every one fully verified** (Ruder's gradient-descent overview 5/5, Dropout 4/4, BatchNorm 5/5, ResNet 5/5), about 5–6 minutes each.
- 43 tests pass.

**Choices and why**
- **Grow the existing Next.js dashboard into the web app** instead of starting a new project: same backend, same styles, one thing to run.
- **Flashcards write the Spaced Repetition plugin's own `<!--SR:...-->` format**: reviews count in Obsidian and in the browser, and no second schedule can go out of sync. A card edited in Obsidian is never overwritten (the file wins).
- **Did not grade any cards while testing**: that would have changed your real review schedule. Grading is covered by unit tests on temporary decks.
- **Display math normalised before rendering** (`$$` on its own lines): Obsidian accepts inline-style `$$...$$` but the web Markdown parser doesn't. Without it only 20 of 138 formulas rendered.
- **Wikilink paths are URL-encoded**: note names contain spaces, which break Markdown links.
- **Developer mode in Chrome was left to you**: it's a browser security setting.
- **Graph colours match Obsidian's graph settings** (gold hubs, purple topics, blue/green/orange subjects), so both views read the same way.
- **The web preview server is stopped after each check**: it competes with the key-points batch for the CPU.

## 2026-10-17 · 13:00-14:00
**Done**
- Restarted the backend and the batch after the 12:55 Windows restart, and set up this hourly decisions log.
- Gold set grew from 64 to **165 AI-audited sentences** (DSA and ML topic notes added): **90.7% strict / 99.1% lenient precision, 1 wrong sentence left in notes, 83% of wrong drafts caught, 84% of removed sentences were true**.
- Fixes found while labelling:
  - Meta-sentences about "the provided passages" are dropped.
  - The sentence splitter no longer breaks at name initials ("Vladimir N. Vapnik").
  - Extraction handles `[` inside sentences.
  - Job-queue race fixed: a client connecting at the moment a job finished could miss "done".
- Batch restarted on the fixed code: 3 topics left, then key points.
- Obsidian was showing a new empty vault ("Obsidian Vault", created 13:18 in OneDrive\Documents after the restart). I closed and relaunched Obsidian on Michael Vault. The empty vault is left for you to delete.
- The embedding backfill finished (the last 351 passages): vector search now covers the whole vault.

**Choices and why**
- **Stable sentence IDs** (hash of note + sentence) instead of row numbers: re-extracting renumbered everything and would have mislabelled 64 sentences. Migrated the old labels from git history.
- **Fragments from the splitting bug are labelled "partly", not "correct"**: honest numbers, even though the text was not false.
- **Over-removal (84%) is reported, not tuned away.** Part of it is correct behaviour (a true sentence with no supporting quote among the selected passages *should* go). The next lever is better evidence selection, not a lower threshold.
- **Didn't delete the stray empty vault**: it's yours, it's harmless, and deleting files is your call.
- **Rewrote `metatron.py` with the file editor** after finding invisible control characters (`\b` turned into backspace by the shell). Scanned every source file afterwards: none left.

## 2026-10-17 · 12:00-13:00
**Done**
- Chrome/Edge extension: suggests the library topic for the article being read; one click adds a link note (name + URL) to that topic. Backend `host/raziel.py`, API `/api/v1/classify|links|topics|token`, hubs show a "Reading list" per topic, links get a lighter subject colour in the graph.
- Live test: modular inverse → Number Theory › Modular arithmetic, Fenwick tree → DSA › Range queries, LSTM → ML › Deep learning, Dijkstra → DSA › Graphs; a pasta recipe correctly gets no pop-up. The add-link flow writes the note and updates the hub.
- Investigated the stop at 12:55: **Windows was restarted from the Start menu** (event 1074, clean restart, not a crash). Restarted the backend and the batch; finished work was kept.

**Choices and why**
- **Raw similarity instead of softmax "confidence"** to decide. Softmax spreads probability over neighbouring topics (modular inverse got only 0.28 and would have gone to the Inbox); cosine similarity separates real matches (0.82–0.87) from unrelated pages (~0.55). Thresholds: < 0.65 no pop-up, < 0.75 Inbox.
- **Link note = name + URL only** (your choice): fast, no LLM, no clutter.
- **Token required** for every extension call, readable only from Obsidian: so no other web page can write into the vault.
- **Database lock made re-entrant (RLock)** after a second deadlock (`topic_centroids` read the DB inside an open connection). A nested call now waits a moment instead of freezing the backend.
- **LLM calls retry on timeouts and wait up to 20 min**: one topic (Unsupervised learning) failed when the API and the batch shared Ollama on a busy CPU. It is retried automatically in the restarted batch.

## 2026-10-17 · 10:30-12:00
**Done**
- Persistent job queue (`jobs.py`), vault watcher (`watcher.py`), nightly scheduler (02:00), citation re-check (`provenance.py`: 85/86 quotes still match), API v0.2.
- Index backfills missing embeddings after an interrupted run.
- Plugin: `obsidian://michael-add` / `michael-ask` links, a bookmarklet, and commands to re-index and check citations.

**Choices and why**
- **SQLite-backed queue instead of Redis/Celery**: nothing extra to install on Windows, survives restarts, and one worker at a time is fastest because the models share one CPU.
- **The file always wins**: the vault (Markdown) is the source of truth, and the database is a rebuildable index. Edits in Obsidian can never be overwritten by the backend.
- **Moved my early test copy of the Transformer notes to `.trash`** (recoverable) rather than deleting it.
- Found that **the laptop slept because of a 3-hour idle timer while plugged in**, not because of the lid. Gave you the setting; I don't change system settings myself.

## 2026-10-17 · 03:00-10:30
**Done**
- Vault index (SQLite FTS5 + vectors, RRF), LLM/NLI result caches, WAL mode.
- Gold-set evaluation: 64 sentences audited: **0 wrong sentences reached a note, 4/4 wrong drafts caught, 93.2% strict precision, 61.5% over-removal**.
- Fixes: LaTeX broken by JSON escapes (`\t` → tab), quote windows ranked by meaning as well as words, wider citation correction.

**Choices and why**
- **Labels marked `claude-audit`, not "human"**: honest metrics. You spot-check 15 to measure agreement.
- **Over-removal was the main weakness**, so I fixed its three causes (LaTeX corruption, "our model" context, paraphrase) instead of loosening thresholds, which would hurt precision.

## 2026-10-17 · 00:00-03:00
**Done**
- Switched the writer to **qwen2.5:7b**, the checker to **DeBERTa-v3-large** (benchmarked 5 models on SciFact), Canvas maps, dense concept-link graph (1,083 Mentions links), dark theme.

**Choices and why**
- **Large checker: 99% precision / 41% recall vs 95% / 29%** for base, at ~3× cost. Quotes are short, so it costs only seconds per note. MiniCheck was slower and worse here.
- **Rejected int8 quantisation**: only 1.4× faster but changed verdicts by up to 0.93 probability.
- **Found the float16-on-CPU slowdown** (newer transformers load half precision by default): forcing float32 made checking 9.3× faster with identical accuracy.
