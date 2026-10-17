// "Michael trust" side panel: every sentence of the open Michael note with its verdict, score, quote and source.
// Parsed from the note itself (the file is the source of truth, so it also works with the backend off); the same
// format learning.parse_note_claims stores in the database.
import { ItemView, MarkdownView, TFile, WorkspaceLeaf } from "obsidian";

export const TRUST_VIEW = "michael-trust";

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
    head.createSpan({ cls: "michael-trust-sentence", text: r.sentence });
    if (r.entailment !== null) head.createSpan({ cls: "michael-trust-score", text: r.entailment.toFixed(2) });
    if (r.quote) el.createEl("blockquote", { cls: "michael-trust-quote", text: r.quote });
    const meta = el.createDiv({ cls: "michael-trust-meta" });
    if (r.source) this.link(meta, r.source, file);
    if (r.detail) meta.createSpan({ text: ` · ${r.detail}` });
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
