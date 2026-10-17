# Decisions log

What was done each hour, the choices made, and why. Newest first. Times are local (IST).

---

## 2026-10-17 · 19:30-21:00 (today's plan, blocks 1-4)
**Done**
- **Topic rewrites (overnight batch): 5 of 23 so far, all replaced the old note.**

  | Topic | Old (verified / sources) | New |
  |---|---|---|
  | GCD | 6 / 1 | 13 / 4 |
  | Primes | 2 / 2 | 10 / 3 |
  | Modular arithmetic | 6 / 1 | 6 / 2 |
  | Arithmetic functions | 5 / 2 | 8 / 4 |
  | Orders and primitive roots | 3 / 2 | 9 / 6 |

  Old notes are in `Number Theory/Archive/`.
- **Precision gate:**
  - `eval/gate.py` re-judges the labelled sentences with the current verifier; `pytest -m eval` runs it, and normal test runs skip it.
  - Gold baseline: strict **91.8%**, lenient **99.5%**, 1 wrong sentence accepted. Floors are set at 91.5% / 99%.
- **Trust side panel (Obsidian):** every sentence of the open note with its verdict, score, quote and source, plus disputes; clicking a row jumps to the sentence. It parses the note itself, so it works without the backend. Tested on the new GCD note: 13 of 13 rows parsed.
- **Contradiction flags:** another source's passage with contradiction ≥ 0.90 and entailment < 0.10 is shown under the footnote and stored in a new `note_claims.conflict` column; `/claims?conflicts=true` lists them.
- **Recall work:**
  - The pronoun-substitution hypothesis was **disproved by data**: only 6 of 79 lost correct drafts start with a pronoun, and none passed after substitution.
  - The real causes are compound sentences, and evidence truncated to 1,500 characters in the test set.
  - Added compound-sentence proving: the sentence is split, each part gets the subject, and every part must be proven.
  - The baseline drafts are now re-judged against their notes' full evidence (rebuilt deterministically, no LLM).
- 67 tests pass; committed as `073ee73`.

**Choices and why**
- **New verifier features ship off** (`MICHAEL_DECOMPOSE`, `MICHAEL_CONFLICT_CHECK`, `MICHAEL_DECONTEXTUALISE`) until the gate shows recall up with no precision loss. A feature that sounds right is not evidence.
- **The trust panel reads the note, not the database:** the note file is the source of truth, and the panel then also works offline.

## 2026-10-17 · 18:35-19:30
**Done**
- **About 80 pages from trusted subject-specific sites** (you asked for more than Wikipedia; nothing existing removed):
  - CP: Princeton *Algorithms* (14 chapters) and the USACO Guide (8 modules).
  - Number Theory: Stanford's number theory notes (18), Brilliant (23) and the Prime Pages (1).
  - ML: Stanford CS231n (7), Distill (3), Lil'Log (4) and colah's blog (1).
  - Each site was test-extracted first: Codeforces and AoPS block downloads, MathWorld comes through almost empty, ProofWiki is cluttered and Google's ML crash course is too thin, so those were skipped.
- **Builder improvements:**
  - `url:` items labelled by site; a per-page title override for CS231n, whose pages share one title.
  - Clean titles for Princeton pages; USACO code rebuilt line by line from its per-line page elements (29 of 29 blocks).
  - An XML-declaration parsing fix (colah's blog).
  - **Merge-safe `state.json` saves**, so fetching can run alongside the batch.
- **Vault:** 426 notes and 7,697 links, with 1 unlinked note (it was 308 notes and 3,607 links at 18:00).
- **"Replace old notes if the new ones are better":** a new `retopics` step rewrites every topic overview that gained sources. The rewrite replaces the current note only if it verifies at least as many sentences and either verifies more or uses more sources. The old note goes to `<Subject>/Archive/`, which is excluded from the claims index.
- **Writer:** one sentence per algorithm step, and up to 14 sentences for overviews. The Geometry rewrite verified only 1 sentence because the writer compressed whole algorithms into single sentences that couldn't be proven against one quote.
- Backend restarted on the new code; 59 tests pass.

**Choices and why**
- **Source articles are never replaced, only the generated overviews:** existing notes cite quotes inside the sources, so deleting or swapping a source would break those citations.
- **The batch log now goes through `cmd`:** PowerShell 5.1 redirection had been writing UTF-16, which made the log unreadable.
- **Topic rewrites run before the remaining key points:** overviews are what you read first, and they gained the most from the new sources.

## 2026-10-17 · 18:20-18:35
**Done**
- Evening batch resumed: overview notes for the 2 new topics, then 72 key-points notes (about 7 h).
- **The Geometry overview came out thin:** 0/2 verified, 2 partial, and 4 sentences removed, including a wrong dot-product formula. The verifier did its job, but the evidence came from only 2 of the 6 articles.
- **Fix:** topic notes now also search with every article's title, and keep up to 12 passages instead of 8, so each article contributes evidence. 59 tests pass.
- Both new topic notes are queued to be rewritten once the batch finishes (`scripts/after_batch.ps1`, `scripts/redo_topics.py`).

**Choices and why**
- **The rewrite waits until the batch is finished**, because two build processes would overwrite each other's `library/state.json`. The first waiter used `wmic`, which isn't available here and could have fired early; it was stopped and replaced by a PowerShell one that needs two idle checks in a row, since the batch has a short gap between topics and key points.
- **The thin note was left in place, not hidden:** what it shows is verified or marked partial, and it will be replaced automatically.

## 2026-10-17 · 18:00-18:20 (sprint wrap-up)
**Done**
- **Controlled baseline, 3B writer** (112 drafts, all labelled `claude-audit`):
  - Without the verifier: 90.2% correct, 8.0% partly, 1.8% wrong.
  - With the verifier: **98.5% correct, 1.5% partly, 0% wrong.**
  - Both wrong sentences were removed: "Dijkstra runs in O(m+n)" and a misattributed author contribution.
  - 36 of 101 correct drafts were also dropped; in the full pipeline, re-citation recovers most of them.
- **Number Theory, same treatment as cp:**
  - 34 new nodes (Wikipedia and cp), chosen mainly from the concepts the existing articles link to most (GCD, coprime integers, integer factorization...); 9,048 of 9,048 formulas render.
  - The Wikipedia articles' own links became wikilinks across all subjects (1,010 links in 73 articles).
- **Backend restarted:** `/claims`, `/flashcards/stats`, `/calibration`, the maths checker with its upgrade rule, and the non-blocking classifier are live. Classify takes about 0.1 s.

**Choices and why**
- **Labels were judged by what is true in the source, not by the verifier's verdict.** Citing the wrong passage but stating a true fact counts as correct, so the comparison measures content, not citation format.
- **New nodes were chosen by link counts.** A concept that 14-20 library articles already link to (e.g. *Coprime integers*) is a gap in the graph; adding it connects many existing notes at once.

## 2026-10-17 · 17:30-18:10
**Done**
- **cp-algorithms notes repaired** (`scripts/polish_sources.py`, rebuilt from each article's original page; the wording is untouched):
  - Code indentation restored and marked as C++ (314 of 318 blocks).
  - "Practice Problems" lists added back (57 notes).
  - "¶" removed from headings.
  - The authors' own links to other library articles became wikilinks (134 links in a "Linked in the article" section).
- **34 new cp-algorithms nodes**, chosen from pages the existing articles link to, plus core CP topics. Two new topics: *Geometry* and *Combinatorics and games*. All 34 saved; formulas render.
- **Links rebuilt:** related articles, 1,148 mention links, hubs, graph colours, canvases. The vault went from about 220 notes and 2,100 links to 308 notes and 3,607 links; 1 note has no links.
- Committed `df62734`. The 3B baseline is on its last notes.

**Choices and why**
- **Author links over model-inferred links:** a link the article's author wrote is a fact about the source. Embedding neighbours are only a guess, so both are kept but labelled separately.
- **Practice lists stop at "Contributors" and skip GitHub links:** the first run pulled in the page's contributor list. It was caught on inspection, the notes were restored from a backup, and the run was repeated.
- **No LLM work this hour** (the overview notes and flashcards for the new topics are left for the evening batch), so the 3B baseline measurement wasn't slowed.

## 2026-10-17 · 16:30-17:30
**Done**
- **Maths benchmark (400 pairs) finished.** Wrong formulas accepted: NLI 2.0% → NLI+maths 1.0%. Wrong numbers accepted: 0% → 0%. True sentences kept: unchanged (91.0%). On near-verbatim edits, NLI already notices most changes.
- **Harder benchmark: the same formula written differently** (150 pairs; SymPy rewrites the formula into an equivalent form, e.g. expanded or factored, and the negatives are rewritten mutations):

  | | True kept | Wrong accepted |
  |---|---|---|
  | NLI | 56.0% | 2.0% |
  | NLI + maths | **69.3%** | **0%** |

  This is where text-only verification fails and the maths check shines.
- **Upgrade rule:** a PARTIAL sentence (0.40-0.70) becomes SUPPORTED only when *every* formula in it is proven equivalent to the evidence. It rescued 20 of the true sentences and none of the wrong ones. Config `MICHAEL_MATH_UPGRADE` (on).
- **Controlled baseline, 7B writer** (86 draft sentences, all labelled):
  - Without the verifier: 90.7% correct, 9.3% partly, 0% wrong.
  - With the verifier: 95.2% correct, 4.8% partly, 0% wrong.
  - 19 of 78 correct drafts were dropped. A 3B writer is running as a stress test.
- **Extension speed:**
  - The first suggestion after a vault change took 11.7 s (the topic vectors were rebuilt on the request path). The classifier now answers from the previous vectors while it rebuilds in the background.
  - The extension pre-classifies 3 s after an article loads, so the card appears instantly at the 20 s mark.
  - The page is read once (textContent, capped at about 1,200 words) instead of on every scroll event.
  - Settings are cached in memory.

**Choices and why**
- **The upgrade requires *all* formulas proven, and numbers alone never count.** A sentence can't be promoted on the strength of one formula while another part is unchecked.
- **Equivalence pairs were filtered to plain algebra.** In CS articles, `+` can mean string concatenation and brackets mean array indexing, where SymPy's rewrites would change the meaning. Those were excluded so the benchmark doesn't reward wrong rewrites.
- **The baseline reports that the 7B writer rarely makes outright errors.** That's the honest finding. So the verifier's measurable value at 7B is precision (fewer imprecise sentences) and provenance, not catching wrong ones. The 3B run tests whether that changes with a weaker writer.

## 2026-10-17 · 15:30-16:30 (3.5-hour sprint: database + baseline + maths-aware checking, deadline 19:12)
**Done**
- **Database completion (Phase 2B):**
  - Every sentence of every generated note is now queryable (256 sentences, 40 notes: 191 verified, 14 partial, 51 removed).
  - A flashcard review log with streak and retention stats.
  - The 247 gold labels are in the database, with automatic threshold calibration.
  - New endpoints `/api/v1/claims`, `/flashcards/stats` and `/calibration`; a `/claims` explorer page in the web app.
- **Maths-aware verification (`ophaniel.py`):**
  - Formulas are parsed from LaTeX with SymPy and checked for equivalence by evaluation at random points.
  - Big-O bounds are compared by growth rate.
  - Every number in a claim must appear in its evidence (also as words: "eleven", "twice").
  - A contradiction downgrades a sentence to unsupported. 12 unit tests.
- **Baseline:** drafts for 14 notes regenerated *without* the verifier (86 sentences; cached prompts return the original drafts). Labelling them is next.
- **Maths benchmark:** 400 sentences from the library (99 formula, 301 number), each with a copy changed in one quantity. Running.
- The key-points batch is paused for the sprint (resumes afterwards; nothing lost).

**Choices and why**
- **Equivalence by random evaluation, not `simplify()`**: simplify often fails on equal expressions; evaluating both at several random points is fast and reliable for these.
- **"Unchecked" is never a failure**: only a formula over the same symbols that evaluates differently counts as a contradiction, so the checker can only remove errors, never block true sentences it doesn't understand.
- **The benchmark's wrong claims change the growth rate, not just a constant**: `O(1)` → `O(3)` isn't wrong, and counting it as an error would have flattered the checker.
- **Calibration result reported as-is**: no threshold reaches 95% strict precision, because the remaining errors are imprecise wording, not low entailment. Threshold tuning is the wrong lever there.

## 2026-10-17 · 15:00-16:00
**Done**
- **Flashcards: one card per verified fact.** BERT's 7 verified facts had produced 1 card, because the model stopped after the first question. The schema now demands exactly N cards, and skipped facts are retried. All 38 existing decks were rebuilt; every deck checked came out one card per fact (e.g. 5/5, 7/7). Review history from the Spaced Repetition plugin is kept.
- **Extension 0.2:**
  - Alt+Shift+M asks about any page immediately.
  - A green ✓ badge shows when the page is already saved.
  - One classification per page per browser session.
  - Single-page sites are followed as you navigate.
  - An offline card appears when the backend isn't running.
  - The backend skips classifying badge-only checks.
  - You reloaded the extension.
- Web app: research-run pages render their note (math, footnotes).
- Key points: 12/84 written, every sentence verified so far; they resume after the deck rebuild.

**Choices and why**
- **Diagnosed the cards before changing them.** I printed what the model returned and why each question was rejected: it was stopping early, not getting filtered. So the fix is in the request (exact count), not in loosening the filters.
- **Rebuilding decks keeps review history** (matched by answer text): you may already have reviewed cards in Obsidian.
- **Session cache in the extension instead of the backend**: the card and the toolbar button run in the same browser, so caching there also saves the network round-trip.

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
