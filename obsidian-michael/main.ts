import { App, Editor, MarkdownView, FileSystemAdapter, Modal, Notice, Plugin, PluginSettingTab, Setting, TFile, normalizePath, requestUrl } from "obsidian";
import { ChildProcess, spawn } from "child_process";
import { TRUST_VIEW, TrustView } from "./trust";
import { CHECK_VIEW, CheckView, CheckResult, proseOf } from "./check";

interface MichaelSettings {
  backendUrl: string;
  outputFolder: string;
  useVault: boolean;
  sources: string[];
  autoStart: boolean;
  backendCommand: string;
}

const DEFAULTS: MichaelSettings = {
  backendUrl: "http://127.0.0.1:8765",
  outputFolder: "Michael",
  useVault: true,
  sources: ["wikipedia", "arxiv", "openalex", "stackexchange", "cpalgorithms"],
  autoStart: true,
  backendCommand: "michael",   // scripts/setup_obsidian.py writes the full path to .venv/Scripts/michael.exe
};

// a browser bookmark whose URL is this sends the current page to Michael (through the michael-add link handler)
const BOOKMARKLET = "javascript:location.href='obsidian://michael-add?url='+encodeURIComponent(location.href)";

interface RunEvent {
  run_id: string;
  stage: string;
  detail: string;
  t: number;
}

export default class MichaelPlugin extends Plugin {
  settings: MichaelSettings = DEFAULTS;
  statusEl: HTMLElement | null = null;
  backend: ChildProcess | null = null;
  busy = false;

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.statusEl = this.addStatusBarItem();

    this.addRibbonIcon("search-check", "Michael: research a question", () => this.askQuestion());

    this.addCommand({
      id: "research-question",
      name: "Research a question (evidence-locked note)",
      callback: () => this.askQuestion(),
    });

    this.addCommand({
      id: "research-selection",
      name: "Research the selected text",
      editorCallback: (editor: Editor) => {
        const q = editor.getSelection().trim();
        if (!q) return new Notice("Select a question first.");
        this.startRun(q);
      },
    });

    this.addCommand({
      id: "verify-selection",
      name: "Verify selected sentence against the clipboard text",
      editorCallback: async (editor: Editor) => {
        const sentence = editor.getSelection().trim();
        const evidence = (await navigator.clipboard.readText()).trim();
        if (!sentence || !evidence) return new Notice("Select a sentence and copy the evidence text to the clipboard.");
        try {
          const r = await requestUrl({
            url: `${this.settings.backendUrl}/verify`, method: "POST", contentType: "application/json",
            body: JSON.stringify({ sentence, evidence }),
          });
          const v = r.json;
          new Notice(`Michael: ${v.label} (entailment ${v.entailment.toFixed(2)})\n"${v.quote}"`, 12000);
        } catch (e) {
          new Notice(`Michael backend not reachable at ${this.settings.backendUrl}. Run: michael serve`);
        }
      },
    });

    this.addRibbonIcon("file-plus-2", "Michael: add an article", () => this.addArticle());
    this.addCommand({ id: "add-article", name: "Add an article (web, arXiv, PDF) with key points", callback: () => this.addArticle() });
    this.addCommand({ id: "start-backend", name: "Start the backend", callback: () => this.ensureBackend(true) });
    this.addCommand({ id: "reindex", name: "Re-index the vault (search)", callback: () => this.queueJob("index", {}, "Re-indexing the vault") });
    this.addCommand({ id: "check-citations", name: "Check that every citation still matches its source",
                      callback: () => this.queueJob("recheck", {}, "Checking citations - see Michael/Citation check", "Michael/Citation check.md") });
    this.addCommand({ id: "copy-extension-token", name: "Copy extension token (for the Chrome extension)",
                      callback: async () => {
                        if (!(await this.ensureBackend(false))) return new Notice("Michael backend not reachable.");
                        const r = await requestUrl({ url: `${this.settings.backendUrl}/api/v1/token` });
                        await navigator.clipboard.writeText(r.json.token);
                        new Notice("Token copied. Paste it in the Michael extension's Settings.", 8000);
                      } });
    this.addCommand({ id: "copy-bookmarklet", name: "Copy the 'Send page to Michael' browser bookmarklet",
                      callback: async () => {
                        await navigator.clipboard.writeText(BOOKMARKLET);
                        new Notice("Bookmarklet copied. Create a browser bookmark and paste this as its URL.", 10000);
                      } });

    // links from the browser / the web app: obsidian://michael-add?url=...  and  obsidian://michael-ask?q=...
    this.registerObsidianProtocolHandler("michael-add", (p) => {
      if (p.url) this.startArticle(decodeURIComponent(p.url), p.summary !== "0");
    });
    this.registerObsidianProtocolHandler("michael-ask", (p) => {
      if (p.q) this.startRun(decodeURIComponent(p.q));
    });

    // fact-check YOUR writing (a note, or the selection) against the library's source articles
    this.registerView(CHECK_VIEW, (leaf) => new CheckView(leaf));
    this.addRibbonIcon("badge-check", "Michael: fact-check this note", () => this.factCheck());
    this.addCommand({ id: "fact-check-note", name: "Fact-check this note (or the selection) against my library",
                      callback: () => this.factCheck() });
    this.registerEvent(this.app.workspace.on("editor-menu", (menu, editor) => {
      if (editor.getSelection().trim())
        menu.addItem((i) => i.setTitle("Fact-check with Michael").setIcon("badge-check").onClick(() => this.factCheck()));
    }));

    // side panel: verdict, score, quote and source of every sentence in the open Michael note
    this.registerView(TRUST_VIEW, (leaf) => new TrustView(leaf));
    this.addRibbonIcon("shield-check", "Michael: trust panel", () => this.openTrust());
    this.addCommand({ id: "open-trust-panel", name: "Open trust panel (evidence for every sentence)",
                      callback: () => this.openTrust() });

    this.addSettingTab(new MichaelSettingTab(this.app, this));
    this.app.workspace.onLayoutReady(() => this.ensureBackend(false));
  }

  async factCheck() {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    const file = view?.file ?? this.app.workspace.getActiveFile();
    if (!file) return new Notice("Open a note first.");
    const selection = view?.editor.getSelection().trim() ?? "";
    const text = proseOf(selection || (await this.app.vault.cachedRead(file))).trim();
    if (text.split(/\s+/).length < 4) return new Notice("Nothing to check in this note.");
    let leaf = this.app.workspace.getLeavesOfType(CHECK_VIEW)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false)!;
      await leaf.setViewState({ type: CHECK_VIEW, active: true });
    }
    this.app.workspace.revealLeaf(leaf);
    const panel = leaf.view as unknown as CheckView;
    panel.show(file, "Checking every sentence against your library… (can take a minute)");
    if (!(await this.ensureBackend(false))) return panel.show(file, "Michael backend not reachable.");
    try {
      const r = await requestUrl({ url: `${this.settings.backendUrl}/api/v1/check`, method: "POST",
                                   contentType: "application/json", body: JSON.stringify({ text }), throw: false });
      if (r.status !== 200) return panel.show(file, `Check failed (HTTP ${r.status}).`);
      const res = r.json as CheckResult;
      panel.show(file, selection ? "Checked the selection." : "Checked the whole note.", res);
      new Notice(`Michael: ${res.summary.supported}/${res.summary.sentences} sentences supported by your library.`);
    } catch (e) {
      panel.show(file, `Check failed: ${(e as Error).message}`);
    }
  }

  async openTrust() {
    let leaf = this.app.workspace.getLeavesOfType(TRUST_VIEW)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false)!;
      await leaf.setViewState({ type: TRUST_VIEW, active: true });
    }
    this.app.workspace.revealLeaf(leaf);
  }

  onunload() {
    this.backend?.kill();
  }

  async healthy(): Promise<boolean> {
    try {
      const r = await requestUrl({ url: `${this.settings.backendUrl}/health`, throw: false });
      return r.status === 200;
    } catch {
      return false;
    }
  }

  /** Start `michael serve` if it is not already running (and autoStart is on, or the user asked). */
  async ensureBackend(userAsked: boolean): Promise<boolean> {
    if (await this.healthy()) {
      this.setIdle();
      if (userAsked) new Notice("Michael backend is already running.");
      return true;
    }
    if (!this.settings.autoStart && !userAsked) {
      this.setStatus("backend offline");
      return false;
    }
    if (!this.backend) {
      const port = new URL(this.settings.backendUrl).port || "8765";
      this.setStatus("starting backend…");
      try {
        this.backend = spawn(this.settings.backendCommand, ["serve", "--port", port], { windowsHide: true, stdio: "ignore" });
        this.backend.on("exit", () => { this.backend = null; if (!this.busy) this.setStatus("backend offline"); });
        this.backend.on("error", (e) => {
          this.backend = null;
          new Notice(`Michael: could not start the backend (${e.message}). Check "Backend command" in settings.`, 12000);
        });
      } catch (e) {
        new Notice(`Michael: could not start the backend. Check "Backend command" in settings.`, 12000);
        return false;
      }
    }
    for (let i = 0; i < 60; i++) {           // the first start loads Python + FastAPI, give it up to 30 s
      await new Promise((r) => setTimeout(r, 500));
      if (await this.healthy()) {
        this.setIdle();
        return true;
      }
    }
    this.setStatus("backend offline");
    return false;
  }

  setIdle() {
    if (!this.busy) this.setStatus("ready");
  }

  vaultPath(): string | null {
    const a = this.app.vault.adapter;
    return a instanceof FileSystemAdapter ? a.getBasePath() : null;
  }

  askQuestion() {
    new QuestionModal(this.app, (q, urls) => this.startRun(q, urls)).open();
  }

  setStatus(text: string) {
    this.statusEl?.setText(text ? `Michael: ${text}` : "");
  }

  async startRun(question: string, urls: string[] = []) {
    const base = this.settings.backendUrl;
    if (this.busy) return new Notice("Michael is already researching - wait for the current note.");
    if (!(await this.ensureBackend(false))) {
      new Notice(`Michael backend not reachable at ${base}. Run the command "Michael: Start the backend".`, 10000);
      return;
    }
    let runId: string;
    try {
      const r = await requestUrl({
        url: `${base}/research`, method: "POST", contentType: "application/json",
        body: JSON.stringify({ question, urls, sources: this.settings.sources, use_vault: this.settings.useVault,
                               vault_path: this.vaultPath() }),
      });
      runId = r.json.run_id;
    } catch (e) {
      new Notice(`Michael backend not reachable at ${base}.`);
      return;
    }
    new Notice(`Michael is researching: ${question}`);
    this.follow(runId, () => this.saveNote(runId, question));
    this.showKnownFacts(question);              // instant: what Michael already verified, while the run works
  }

  /** Facts already proven by a quote in Michael's notes, closest in meaning to the question (no model run). */
  async showKnownFacts(question: string) {
    try {
      const r = await requestUrl({ url: `${this.settings.backendUrl}/api/v1/facts?q=${encodeURIComponent(question)}&k=6`,
                                   throw: false });
      const facts = (r.json?.facts ?? []) as { fact: string; quote: string; source: string; score: number }[];
      if (!facts.length) return;
      let leaf = this.app.workspace.getLeavesOfType(CHECK_VIEW)[0];
      if (!leaf) {
        leaf = this.app.workspace.getRightLeaf(false)!;
        await leaf.setViewState({ type: CHECK_VIEW, active: true });
      }
      this.app.workspace.revealLeaf(leaf);
      const n = facts.length;
      (leaf.view as unknown as CheckView).show(null, `Already verified (instant) - the full research note is on its way: ${question}`,
        { sentences: facts.map((f) => ({ sentence: f.fact, verdict: "SUPPORTED", entailment: f.score, quote: f.quote, source: f.source })),
          summary: { sentences: n, supported: n, partial: 0, unsupported: 0 } });
    } catch {
      /* instant facts are a bonus: the research run doesn't depend on them */
    }
  }

  /** Show a run's progress in the status bar; call onDone when it finishes. */
  follow(runId: string, onDone: (ev: RunEvent) => Promise<void>) {
    this.busy = true;
    this.setStatus("starting…");
    const es = new EventSource(`${this.settings.backendUrl}/runs/${runId}/events`);
    const stages = ["queued", "plan", "vault", "gather", "search", "rerank", "write", "verify", "repair", "warn",
                    "fetch", "extract", "saved"];
    for (const stage of stages) {
      es.addEventListener(stage, (ev: MessageEvent) => {
        const e: RunEvent = JSON.parse(ev.data);
        this.setStatus(`${e.stage} - ${e.detail}`);
      });
    }
    es.addEventListener("error", (ev: MessageEvent) => {
      if (ev.data) {
        const e: RunEvent = JSON.parse(ev.data);
        new Notice(`Michael failed: ${e.detail}`, 15000);
      }
      this.busy = false;
      this.setIdle();
      es.close();
    });
    es.addEventListener("done", async (ev: MessageEvent) => {
      es.close();
      this.busy = false;
      this.setIdle();
      await onDone(JSON.parse(ev.data));
    });
  }

  addArticle() {
    new ArticleModal(this.app, (target, summary) => this.startArticle(target, summary)).open();
  }

  /** Queue a backend job (index, recheck, ...) and report when it finishes. */
  async queueJob(kind: string, params: Record<string, unknown>, notice: string, openWhenDone?: string) {
    if (!(await this.ensureBackend(false))) return new Notice("Michael backend not reachable.");
    try {
      const r = await requestUrl({
        url: `${this.settings.backendUrl}/api/v1/jobs`, method: "POST", contentType: "application/json",
        body: JSON.stringify({ kind, params: { vault_path: this.vaultPath(), ...params } }),
      });
      new Notice(`Michael: ${notice}`);
      const es = new EventSource(`${this.settings.backendUrl}/api/v1/jobs/${r.json.id}/events`);
      es.onmessage = () => {};
      for (const s of ["index", "recheck", "library"]) {
        es.addEventListener(s, (ev: MessageEvent) => this.setStatus(`${s} - ${JSON.parse(ev.data).detail}`));
      }
      es.addEventListener("done", async () => {
        es.close();
        this.setIdle();
        new Notice(`Michael: ${kind} finished.`);
        if (openWhenDone) await this.app.workspace.openLinkText(openWhenDone, "", true);
      });
      es.addEventListener("error", (ev: MessageEvent) => {
        es.close();
        this.setIdle();
        if (ev.data) new Notice(`Michael ${kind} failed: ${JSON.parse(ev.data).detail}`, 10000);
      });
    } catch (e) {
      new Notice(`Michael: could not start ${kind}.`);
    }
  }

  async startArticle(target: string, summary: boolean) {
    const base = this.settings.backendUrl;
    if (this.busy) return new Notice("Michael is busy - wait for the current run.");
    if (!(await this.ensureBackend(false))) {
      new Notice(`Michael backend not reachable at ${base}. Run the command "Michael: Start the backend".`, 10000);
      return;
    }
    let runId: string;
    try {
      const r = await requestUrl({
        url: `${base}/articles`, method: "POST", contentType: "application/json",
        body: JSON.stringify({ target, summary, vault_path: this.vaultPath() }),
      });
      runId = r.json.run_id;
    } catch (e) {
      new Notice(`Michael backend not reachable at ${base}.`);
      return;
    }
    new Notice(`Michael is adding: ${target}`);
    this.follow(runId, async (ev: any) => {
      // the backend wrote the files straight into this vault; open the key points (or the article itself)
      const s = ev.stats || {};
      const abs: string = ev.note || ev.source_note;
      await this.openVaultFile(abs);
      const math = s.math && s.math.formulas ? ` · ${s.math.rendered ?? "?"}/${s.math.formulas} formulas render` : "";
      new Notice(summary ? `Michael: article saved, ${s.supported}/${s.total} key points verified${math}.`
                         : `Michael: article saved${math}.`, 10000);
    });
  }

  async openVaultFile(absPath: string) {
    const root = this.vaultPath();
    if (!absPath || !root) return;
    const rel = normalizePath(absPath.replace(/\\/g, "/").slice(root.replace(/\\/g, "/").length + 1));
    for (let i = 0; i < 20; i++) {             // give Obsidian a moment to notice the new file
      const f = this.app.vault.getAbstractFileByPath(rel);
      if (f instanceof TFile) return this.app.workspace.getLeaf(true).openFile(f);
      await new Promise((r) => setTimeout(r, 250));
    }
    new Notice(`Saved to ${rel}`);
  }

  async saveNote(runId: string, question: string) {
    const r = await requestUrl({ url: `${this.settings.backendUrl}/runs/${runId}` });
    const run = r.json;
    const folder = normalizePath(this.settings.outputFolder);
    if (!this.app.vault.getAbstractFileByPath(folder)) await this.app.vault.createFolder(folder);
    const base = question.replace(/[\\/:*?"<>|#^[\]]/g, "").slice(0, 60).trim() || "Michael note";
    let path = normalizePath(`${folder}/${base}.md`);
    for (let i = 2; this.app.vault.getAbstractFileByPath(path); i++) path = normalizePath(`${folder}/${base} ${i}.md`);
    const file = await this.app.vault.create(path, run.markdown);
    await this.app.workspace.getLeaf(true).openFile(file);
    const s = run.stats;
    new Notice(`Michael: ${s.supported}/${s.total} sentences verified, ${s.removed} removed.`, 8000);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}

class ArticleModal extends Modal {
  constructor(app: App, private onSubmit: (target: string, summary: boolean) => void) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h3", { text: "Michael - add an article" });
    contentEl.createEl("div", { cls: "setting-item-description",
      text: "Web page, arXiv link or id (LaTeX kept exact), PDF link, or a PDF path. Saved to Sources/." });
    const input = contentEl.createEl("input", { attr: { type: "text", style: "width:100%" } });
    input.placeholder = "https://arxiv.org/abs/1706.03762";
    let summary = true;
    new Setting(contentEl).setName("Also write verified key points")
      .addToggle((t) => t.setValue(true).onChange((v) => (summary = v)));
    const submit = () => {
      const target = input.value.trim();
      if (target) {
        this.close();
        this.onSubmit(target, summary);
      }
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
    new Setting(contentEl).addButton((b) => b.setButtonText("Add").setCta().onClick(submit));
    input.focus();
  }

  onClose() {
    this.contentEl.empty();
  }
}

class QuestionModal extends Modal {
  constructor(app: App, private onSubmit: (q: string, urls: string[]) => void) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h3", { text: "Michael - research a question" });
    const input = contentEl.createEl("textarea", { attr: { rows: "3", style: "width:100%" } });
    input.placeholder = "e.g. How does LACP differ from PAgP?";
    contentEl.createEl("div", { text: "Extra web pages to use as sources (optional, one URL per line):", cls: "setting-item-description" });
    const urlBox = contentEl.createEl("textarea", { attr: { rows: "2", style: "width:100%" } });
    urlBox.placeholder = "https://...";
    const submit = () => {
      const q = input.value.trim();
      const urls = urlBox.value.split(/\s+/).map((u) => u.trim()).filter((u) => /^https?:\/\//.test(u));
      if (q) {
        this.close();
        this.onSubmit(q, urls);
      }
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit();
      }
    });
    new Setting(contentEl).addButton((b) => b.setButtonText("Research").setCta().onClick(submit));
    input.focus();
  }

  onClose() {
    this.contentEl.empty();
  }
}

class MichaelSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: MichaelPlugin) {
    super(app, plugin);
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    new Setting(containerEl).setName("Backend URL").setDesc("Where `michael serve` is running.")
      .addText((t) => t.setValue(this.plugin.settings.backendUrl).onChange(async (v) => {
        this.plugin.settings.backendUrl = v.trim().replace(/\/$/, "");
        await this.plugin.saveSettings();
      }));
    new Setting(containerEl).setName("Start backend automatically").setDesc("Runs `michael serve` when Obsidian opens.")
      .addToggle((t) => t.setValue(this.plugin.settings.autoStart).onChange(async (v) => {
        this.plugin.settings.autoStart = v;
        await this.plugin.saveSettings();
      }));
    new Setting(containerEl).setName("Backend command").setDesc("Path to michael.exe inside the project's .venv.")
      .addText((t) => t.setValue(this.plugin.settings.backendCommand).onChange(async (v) => {
        this.plugin.settings.backendCommand = v.trim();
        await this.plugin.saveSettings();
      }));
    new Setting(containerEl).setName("Output folder").setDesc("Michael's notes are saved here (and never used as sources).")
      .addText((t) => t.setValue(this.plugin.settings.outputFolder).onChange(async (v) => {
        this.plugin.settings.outputFolder = v.trim() || "Michael";
        await this.plugin.saveSettings();
      }));
    new Setting(containerEl).setName("Use my vault as a source").setDesc("Your notes are searched alongside the web sources and cited as [[links]].")
      .addToggle((t) => t.setValue(this.plugin.settings.useVault).onChange(async (v) => {
        this.plugin.settings.useVault = v;
        await this.plugin.saveSettings();
      }));
    const labels: Record<string, string> = {
      wikipedia: "Wikipedia", arxiv: "arXiv papers", openalex: "OpenAlex (paper abstracts)",
      stackexchange: "Stack Exchange (math, cs, stats, Stack Overflow; well-voted answers only)",
      cpalgorithms: "cp-algorithms.com", semanticscholar: "Semantic Scholar (papers; often rate-limited)",
      oeis: "OEIS (integer sequences)",
    };
    for (const src of Object.keys(labels)) {
      new Setting(containerEl).setName(`Source: ${labels[src]}`)
        .addToggle((t) => t.setValue(this.plugin.settings.sources.includes(src)).onChange(async (v) => {
          const s = new Set(this.plugin.settings.sources);
          v ? s.add(src) : s.delete(src);
          this.plugin.settings.sources = [...s];
          await this.plugin.saveSettings();
        }));
    }
  }
}
