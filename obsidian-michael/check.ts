// "Fact-check with Michael": any note you wrote (or a selection) is checked sentence by sentence against your
// library's source articles. Results in a side panel: verdict, the exact quote and its source; click to jump.
import { ItemView, MarkdownRenderer, MarkdownView, Component, TFile, WorkspaceLeaf } from "obsidian";

export const CHECK_VIEW = "michael-check";

export interface CheckSentence {
  sentence: string;
  verdict: string;          // SUPPORTED | PARTIAL | UNSUPPORTED
  entailment: number;
  quote?: string;
  source?: string;          // [[Note#Section]]
  url?: string;
  how?: string[];
}

export interface CheckResult {
  sentences: CheckSentence[];
  summary: { sentences: number; supported: number; partial: number; unsupported: number };
}

/** Markdown -> plain prose for checking: no frontmatter, code, footnote definitions, links syntax or callout marks. */
export function proseOf(md: string): string {
  return md
    .replace(/^---\n[\s\S]*?\n---\n/, "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^\[\^[^\]]+\]:.*$/gm, " ")
    .replace(/\[\^[^\]]+\]/g, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, a, b) => b || a)
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s*>\s?\[![^\]]*\].*$/gm, " ")
    .replace(/^\s*(#+|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/[*_=~`]/g, "");
}

export class CheckView extends ItemView {
  private renderScope: Component | null = null;
  file: TFile | null = null;
  result: CheckResult | null = null;
  status = "";

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
  }

  getViewType() { return CHECK_VIEW; }
  getDisplayText() { return "Michael fact-check"; }
  getIcon() { return "badge-check"; }

  async onOpen() { this.render(); }

  show(file: TFile | null, status: string, result: CheckResult | null = null) {
    this.file = file;
    this.status = status;
    this.result = result;
    this.render();
  }

  render() {
    const root = this.contentEl;
    this.renderScope?.unload();
    this.renderScope = new Component();
    this.addChild(this.renderScope);
    root.empty();
    root.addClass("michael-trust");
    root.createEl("h4", { text: this.file ? `Fact-check: ${this.file.basename}` : "Fact-check" });
    if (this.status) root.createEl("p", { cls: "michael-trust-summary", text: this.status });
    const r = this.result;
    if (!r) return;
    const s = r.summary;
    root.createEl("p", { cls: "michael-trust-summary",
      text: `✓ ${s.supported} supported · ◐ ${s.partial} partial · ✗ ${s.unsupported} not found in your library` });
    for (const c of r.sentences) {
      const cls = { SUPPORTED: "ok", PARTIAL: "partial" }[c.verdict] ?? "removed";
      const el = root.createDiv({ cls: `michael-trust-row is-${cls === "removed" ? "unchecked" : cls}` });
      const head = el.createDiv({ cls: "michael-trust-head" });
      head.createSpan({ cls: "michael-trust-icon", text: { ok: "✓", partial: "◐" }[cls] ?? "✗" });
      head.createSpan({ cls: "michael-trust-sentence", text: c.sentence });
      head.createSpan({ cls: "michael-trust-score", text: c.entailment.toFixed(2) });
      if (c.quote) {
        const q = el.createEl("blockquote", { cls: "michael-trust-quote" });
        MarkdownRenderer.render(this.app, c.quote, q, this.file?.path ?? "", this.renderScope);
      }
      const meta = el.createDiv({ cls: "michael-trust-meta" });
      if (c.source && c.verdict !== "UNSUPPORTED") {
        const m = /^\[\[(.*?)\]\]$/.exec(c.source);
        const a = meta.createEl("a", { text: m ? m[1] : c.source });
        a.onClickEvent((e) => { e.preventDefault(); if (m) this.app.workspace.openLinkText(m[1], "", true); });
      } else if (c.verdict === "UNSUPPORTED") {
        meta.createSpan({ text: "no passage in your library proves this sentence" });
      }
      for (const h of c.how ?? []) meta.createSpan({ cls: "michael-trust-badge is-context", text: h });
      el.onClickEvent((e) => { if ((e.target as HTMLElement).tagName !== "A") this.jumpTo(c.sentence); });
    }
  }

  private jumpTo(sentence: string) {
    if (!this.file) return;
    const view = this.app.workspace.getLeavesOfType("markdown").map((l) => l.view as MarkdownView)
      .find((v) => v.file?.path === this.file?.path);
    if (!view) return;
    const text = view.editor.getValue();
    const words = sentence.split(/\s+/).slice(0, 6).join(" ");
    const i = text.indexOf(words);
    if (i < 0) return;
    const from = view.editor.offsetToPos(i);
    this.app.workspace.setActiveLeaf(view.leaf, { focus: true });
    view.editor.setSelection(from, view.editor.offsetToPos(i + words.length));
    view.editor.scrollIntoView({ from, to: from }, true);
  }
}
