import "./globals.css";
import "katex/dist/katex.min.css";
import type { ReactNode } from "react";
import { Fraunces, Inter } from "next/font/google";
import Header, { Leaf } from "./Header";

export const metadata = { title: "Michael", description: "Evidence-locked research library" };

const serif = Fraunces({ subsets: ["latin"], variable: "--font-serif", display: "swap" });
const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable}`} suppressHydrationWarning>
      <body>
        <Header />
        <main className="wrap">{children}</main>
        <footer className="foot"><Leaf size={14} /> Michael · grown from your trusted sources, checked sentence by sentence</footer>
      </body>
    </html>
  );
}
