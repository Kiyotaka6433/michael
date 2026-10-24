"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const LINKS = [
  ["/library", "Library"], ["/search", "Search"], ["/flashcards", "Flashcards"], ["/quiz", "Quiz"],
  ["/coverage", "Coverage"], ["/graph", "Graph"], ["/claims", "Claims"], ["/runs", "Research"],
];

export function Leaf({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z" />
      <path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12" />
    </svg>
  );
}

export default function Header() {
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<"day" | "dusk">("dusk");

  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem("michael-theme"); } catch {}
    const t = saved === "day" ? "day" : "dusk";            // dark by default
    setTheme(t);
    document.documentElement.dataset.theme = t;
  }, []);

  useEffect(() => setOpen(false), [path]);

  // "/" jumps to search from anywhere (unless you are typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName);
      if (e.key !== "/" || typing) return;
      e.preventDefault();
      const box = document.querySelector<HTMLInputElement>("input[name=q], input[type=search]");
      if (box) box.focus();
      else router.push("/search");
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [router]);

  const toggle = () => {
    const t = theme === "day" ? "dusk" : "day";
    setTheme(t);
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("michael-theme", t); } catch {}
  };
  const active = (href: string) => path.startsWith(href);

  return (
    <header className="top">
      <a href="/" className="brand"><Leaf />Michael</a>
      <nav className={`nav${open ? " open" : ""}`}>
        {LINKS.map(([href, label]) => (
          <a key={href} href={href} className={active(href) ? "active" : ""}>{label}</a>
        ))}
      </nav>
      <button className={`theme-switch ${theme}`} onClick={toggle} role="switch" aria-checked={theme === "dusk"}
              aria-label="Dark mode" title={theme === "day" ? "Switch to dark" : "Switch to light"}>
        <span className="knob">{theme === "day" ? "☀" : "☾"}</span>
      </button>
      <button className="icon-btn menu-btn" onClick={() => setOpen(!open)} aria-label="Menu" aria-expanded={open}>☰</button>
    </header>
  );
}
