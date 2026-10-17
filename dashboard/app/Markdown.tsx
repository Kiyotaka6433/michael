// Renders a vault note: GitHub-flavoured Markdown, footnotes, and LaTeX math with KaTeX.
// Links of the form note:<vault path>#<heading> (resolved [[wikilinks]] from the backend) stay inside the web app.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { noteHref } from "../lib/library";

const CALLOUT_ICON: Record<string, string> = { info: "ℹ", abstract: "📄", warning: "⚠", note: "✎", tip: "💡" };

// Obsidian Markdown -> what remark understands:
//  - display math may sit inline ("$$\begin{equation} ... $$" over several lines): give it its own block
//  - callouts ("> [!info] Title") become a bold first line inside the quote
export function prepare(md: string): string {
  return md
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, inner: string) => `\n\n$$\n${inner.trim()}\n$$\n\n`)
    .replace(/^> \[!(\w+)\]\s*(.*)$/gm, (_, type: string, title: string) =>
      `> **${CALLOUT_ICON[type.toLowerCase()] ?? "▸"} ${title || type}**  `);
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
        urlTransform={(url) => url}
        components={{
          a: ({ href = "", children }) => {
            if (href.startsWith("note:")) {
              const [path, heading] = href.slice(5).split("#");
              return <a href={noteHref(decodeURIComponent(path), heading && decodeURIComponent(heading))} className="wikilink">{children}</a>;
            }
            const external = /^https?:/.test(href);
            return <a href={href} target={external ? "_blank" : undefined} rel="noreferrer">{children}</a>;
          },
        }}
      >
        {prepare(text)}
      </ReactMarkdown>
    </div>
  );
}
