import { App, Modal } from "obsidian";

// Study mode inside Obsidian: questions about one note, made from facts Michael has verified (no model invents them).
export interface QuizQuestion {
  question: string;
  answer: string;
  options: string[];
  kind: string;
  fact: string;
  quote: string;
  source: string;
  note: string;
}

export class QuizModal extends Modal {
  private i = 0;
  private right = 0;

  constructor(app: App, private title: string, private questions: QuizQuestion[]) {
    super(app);
  }

  onOpen() {
    this.modalEl.addClass("michael-quiz");
    this.render();
  }

  private render() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h3", { text: `Quiz: ${this.title}` });
    if (this.i >= this.questions.length) {
      contentEl.createEl("p", { text: `You got ${this.right} of ${this.questions.length}.` });
      const again = contentEl.createEl("button", { text: "Again", cls: "mod-cta" });
      again.onclick = () => {
        this.i = this.right = 0;
        this.render();
      };
      return;
    }
    const q = this.questions[this.i];
    contentEl.createEl("div", { cls: "michael-quiz-progress", text: `Question ${this.i + 1} of ${this.questions.length}` });
    contentEl.createEl("p", { cls: "michael-quiz-question", text: q.question });
    const opts = contentEl.createDiv({ cls: "michael-quiz-options" });
    const after = contentEl.createDiv();
    const buttons = q.options.map((o) => {
      const b = opts.createEl("button", { text: o });
      b.onclick = () => {
        const ok = o === q.answer;
        if (ok) this.right++;
        for (const x of buttons) {
          x.disabled = true;
          if (x.textContent === q.answer) x.addClass("is-right");
          else if (x === b) x.addClass("is-wrong");
        }
        after.createEl("p", { text: ok ? "✓ Correct." : `✗ The answer is ${q.answer}.` });
        after.createEl("p", { cls: "michael-quiz-fact", text: q.fact });
        const quote = after.createEl("blockquote", { text: q.quote.slice(0, 400) + (q.quote.length > 400 ? "…" : "") });
        quote.createEl("div", { cls: "michael-quiz-source", text: `— ${q.source.replace(/^\[\[|\]\]$/g, "")}` });
        const next = after.createEl("button", { text: this.i + 1 < this.questions.length ? "Next" : "Finish", cls: "mod-cta" });
        next.onclick = () => {
          this.i++;
          this.render();
        };
        next.focus();
      };
      return b;
    });
  }

  onClose() {
    this.contentEl.empty();
  }
}
