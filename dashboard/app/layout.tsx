import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "Michael", description: "Evidence-locked research runs" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="top">
          <a href="/" className="brand">Michael</a>
          <span className="muted">evidence-locked research</span>
        </header>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
