import "./globals.css";
import "katex/dist/katex.min.css";
import type { ReactNode } from "react";

export const metadata = { title: "Michael", description: "Evidence-locked research library" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <a href="/library" className="brand">Michael</a>
          <nav className="nav">
            <a href="/library">Library</a>
            <a href="/search">Search</a>
            <a href="/flashcards">Flashcards</a>
            <a href="/">Research runs</a>
          </nav>
          <span className="muted grow-right">every sentence backed by a quote</span>
        </header>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
