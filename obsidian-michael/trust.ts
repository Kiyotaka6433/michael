// "Michael trust" side panel: every sentence of the open Michael note with its verdict, score, quote and source.
// Parsed from the note itself (the file is the source of truth, so it also works with the backend off); the same
// format learning.parse_note_claims stores in the database.
import { Component, ItemView, MarkdownRenderer, MarkdownView, TFile, WorkspaceLeaf } from "obsidian";

export const TRUST_VIEW = "michael-trust";

// footnote details shown as small badges: [text in the footnote, badge, css class]
const BADGES: [string, string, string][] = [
  ["formulas proven equivalent", "∑ proven", "is-math"],
  ["formulas and numbers checked", "∑ checked", "is-math"],
  ["in the context of its paragraph", "¶ paragraph", "is-context"],
  ["judged with its source title as context", "title context", "is-context"],
  ["proven in", "proven in parts", "is-parts"],
  ["near-verbatim", "near-verbatim", "is-context"],
];

export interface TrustRow {
  sentence: string;
  status: string;           // SUPPORTED | PARTIAL | REMOVED | UNKNOWN
  entailment: number | null;
  quote: string;
  source: string;           // [[Note#Section]] or [title](url)
  detail: string;           // "in the context of its paragraph", "formulas proven equivalent", ...
  conflictSource: string;
  conflictQuote: string;
}

const FOOT = /^\[\^(\d+)\]: "(.*)" - (\[\[.*?\]\]|\[.*?\]\(.*?\)) · (\w+)(.*?)\(entailment ([\d.]+)\)(.*)$/gm;
const SENT = /(==)?((?:[^\[\n]|\[(?!\^))+?)(==)?\[\^(\d+)\]/g;
const CONFLICT = /⚠ (\[\[.*?\]\]) appears to disagree: "(.*)" \(contradiction/;

export function parseTrust(text: string): TrustRow[] {
  const feet = new Map<string, RegExpExecArray>();
  for (const m of text.matchAll(FOOT)) feet.set(m[1], m as RegExpExecArray);
  const body = (text.split("> Verifier:")[1] ?? "").split("\n## ")[0];
  const rows: TrustRow[] = [];
  for (const m of body.matchAll(SENT)) {
    const f = feet.get(m[4]);
    const c = f ? CONFLICT.exec(f[7]) : null;
    rows.push({
      sentence: m[2].trim().replace(/^[⚠✗ ]+/, "").replace(/^=+|=+$/g, ""),
      status: f ? f[4].toUpperCase() : "UNKNOWN",
      entailment: f ? parseFloat(f[6]) : null,
      quote: f ? f[2] : "",
      source: f ? f[3] : "",
      detail: f ? f[5].replace(/^[\s·]+|[\s·]+$/g, "") : "",
      conflictSource: c ? c[1] : "",
      conflictQuote: c ? c[2] : "",
    });
  }
  const removed = text.split("## Removed claims")[1];
  if (removed) {
    for (const m of removed.split("\n## ")[0].matchAll(/^- ~~(.*)~~$/gm)) {
      rows.push({ sentence: m[1], status: "REMOVED", entailment: null, quote: "", source: "", detail: "",
                  conflictSource: "", conflictQuote: "" });
    }
  }
  return rows;
}

export class TrustView extends ItemView {
  private renderScope: Component | null = null;   // owns the rendered quotes (maths, bold); replaced on each render

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
  }

  getViewType() { return TRUST_VIEW; }
  getDisplayText() { return "Michael trust"; }
  getIcon() { return "shield-check"; }

  async onOpen() {
    this.registerEvent(this.app.workspace.on("file-open", () => this.render()));
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.render()));
    this.registerEvent(this.app.vault.on("modify", (f) => {
      if (f === this.app.workspace.getActiveFile()) this.render();
    }));
    await this.render();
  }

  async render() {
    const root = this.contentEl;
    const file = this.app.workspace.getActiveFile();
    if (!file || file.extension !== "md") return;      // keep showing the last note while the panel has focus
    const text = await this.app.vault.cachedRead(file);
    const rows = parseTrust(text);
    this.renderScope?.unload();
    this.renderScope = new Component();
    this.addChild(this.renderScope);
    root.empty();
    root.addClass("michael-trust");
    root.createEl("h4", { text: file.basename });
    if (!rows.length) {
      root.createEl("p", { cls: "michael-trust-empty", text: "Not a Michael note: no verified sentences here." });
      return;
    }
    const count = (s: string) => rows.filter((r) => r.status === s).length;
    const conflicts = rows.filter((r) => r.conflictSource).length;
    root.createEl("p", { cls: "michael-trust-summary",
      text: `✓ ${count("SUPPORTED")} verified · ◐ ${count("PARTIAL")} partial · ✗ ${count("REMOVED")} removed` +
            (conflicts ? ` · ⚠ ${conflicts} disputed` : "") });
    for (const r of rows) this.row(root, file, r);
  }

  private row(root: HTMLElement, file: TFile, r: TrustRow) {
    const cls = { SUPPORTED: "ok", PARTIAL: "partial", REMOVED: "removed" }[r.status] ?? "unknown";
    const el = root.createDiv({ cls: `michael-trust-row is-${cls}${r.conflictSource ? " is-conflict" : ""}` });
    const head = el.createDiv({ cls: "michael-trust-head" });
    head.createSpan({ cls: "michael-trust-icon", text: { ok: "✓", partial: "◐", removed: "✗" }[cls] ?? "?" });
    this.md(head.createSpan({ cls: "michael-trust-sentence" }), r.sentence, file);
    if (r.entailment !== null) head.createSpan({ cls: "michael-trust-score", text: r.entailment.toFixed(2) });
    if (r.quote) this.md(el.createEl("blockquote", { cls: "michael-trust-quote" }), r.quote, file);
    const meta = el.createDiv({ cls: "michael-trust-meta" });
    if (r.source) this.link(meta, r.source, file);
    for (const [needle, badge, cls] of BADGES) {
      if (r.detail.includes(needle)) meta.createSpan({ cls: `michael-trust-badge ${cls}`, text: badge });
    }
    if (r.conflictSource) {
      const c = el.createDiv({ cls: "michael-trust-conflict" });
      c.createSpan({ text: "⚠ " });
      this.link(c, r.conflictSource, file);
      c.createSpan({ text: ` appears to disagree: "${r.conflictQuote}"` });
    }
    if (r.status !== "REMOVED") el.onClickEvent((e) => {
      if ((e.target as HTMLElement).tagName !== "A") this.jumpTo(file, r.sentence);
    });
  }

  // quotes and sentences contain LaTeX and Markdown: render them as Obsidian would
  private md(el: HTMLElement, text: string, file: TFile) {
    MarkdownRenderer.render(this.app, text, el, file.path, this.renderScope ?? this);
    const p = el.querySelector(":scope > p");          // one paragraph: unwrap so it flows inline
    if (p && el.children.length === 1) el.replaceChildren(...Array.from(p.childNodes));
  }

  private link(parent: HTMLElement, md: string, from: TFile) {
    const wiki = /^\[\[(.*?)\]\]$/.exec(md);
    const ext = /^\[(.*?)\]\((.*?)\)$/.exec(md);
    const a = parent.createEl("a", { text: wiki ? wiki[1] : ext ? ext[1] : md });
    a.onClickEvent((e) => {
      e.preventDefault();
      if (wiki) this.app.workspace.openLinkText(wiki[1], from.path, true);
      else if (ext) window.open(ext[2]);
    });
  }

  private jumpTo(file: TFile, sentence: string) {
    const view = this.app.workspace.getLeavesOfType("markdown").map((l) => l.view as MarkdownView)
      .find((v) => v.file?.path === file.path);
    if (!view) return;
    const editor = view.editor;
    const text = editor.getValue();
    const i = text.indexOf(sentence.slice(0, 60));
    if (i < 0) return;
    const from = editor.offsetToPos(i);
    const to = editor.offsetToPos(i + Math.min(sentence.length, text.length - i));
    this.app.workspace.setActiveLeaf(view.leaf, { focus: true });
    editor.setSelection(from, to);
    editor.scrollIntoView({ from, to }, true);
  }
}
