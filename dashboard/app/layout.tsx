import "./globals.css";
import "./redesign.css";
import "./fx/fx.css";
import "katex/dist/katex.min.css";
import { Suspense, type ReactNode } from "react";
import { JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import Header, { Leaf } from "./Header";
import Fx from "./fx/Fx";

export const metadata = { title: "Michael", description: "Evidence-locked research library" };

const sans = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} data-theme="dusk" suppressHydrationWarning>
      <body>
        <Suspense fallback={null}><Fx /></Suspense>
        <Header />
        <main className="wrap">{children}</main>
        <footer className="foot"><Leaf size={14} /> Michael · grown from your trusted sources, checked sentence by sentence</footer>
      </body>
    </html>
  );
}
