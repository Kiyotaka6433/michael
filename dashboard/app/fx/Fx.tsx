"use client";
// Site-wide interaction layer, mounted once in the layout so every page gets it without its own code:
//  - curtain page transitions (and in-app navigation instead of full reloads)
//  - custom cursor: a dot plus a lagging ring that grows over anything clickable
//  - staggered scroll reveal for cards, rows, claims and topics (also for content that loads later)
//  - spotlight glow on cards, magnetic primary buttons, scrambled-text titles, scroll progress bar
// Everything is transform/opacity based, and off for touch screens or prefers-reduced-motion.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Leaf } from "../Header";

const REVEAL = ".wrap .card, .wrap .stat, .wrap .claim, .wrap tbody tr, .wrap details.topic, .wrap a.hit, .wrap .quiz-options button, .wrap .flashcard";
const SPOT = ".card, .stat, .sc-card, a.hit, .ask-fact, .step";
const MAGNET = ".btn.primary, button.primary, .cta, .row > button:first-of-type:only-child";
const TITLES = ".page-title, .sec-title";
const GLYPHS = "abcdefghijklmnopqrstuvwxyz0123456789#%&*+=<>/";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function scramble(el: HTMLElement) {
  if (el.dataset.fxDone || el.children.length || reduced()) return;
  el.dataset.fxDone = "1";
  const final = el.textContent || "";
  const t0 = performance.now(), dur = 700;
  const step = (t: number) => {
    const p = Math.min(1, (t - t0) / dur);
    const fixed = Math.floor(final.length * p);
    el.textContent = final.slice(0, fixed) + [...final.slice(fixed)]
      .map((c) => (c === " " ? " " : GLYPHS[Math.floor(Math.random() * GLYPHS.length)])).join("");
    if (p < 1) requestAnimationFrame(step);
    else el.textContent = final;
  };
  requestAnimationFrame(step);
}

export default function Fx() {
  const path = usePathname();
  const search = useSearchParams().toString();   // a string: stable across re-renders
  const router = useRouter();
  const [curtain, setCurtain] = useState<"idle" | "cover" | "reveal">("idle");
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const pending = useRef<number>(0);

  // ---- page transitions: cover, navigate in-app, reveal when the new route renders
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest("a");
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (a.target === "_blank" || a.hasAttribute("download") || a.closest(".md-body .footnotes")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin) return;
      if (url.pathname === location.pathname && url.search === location.search) return;   // same page / #hash
      e.preventDefault();
      if (reduced()) return router.push(url.pathname + url.search + url.hash);
      setCurtain("cover");
      clearTimeout(pending.current);
      pending.current = window.setTimeout(() => router.push(url.pathname + url.search + url.hash), 420);
      window.setTimeout(() => setCurtain((c) => (c === "cover" ? "reveal" : c)), 5000);   // never stuck
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [router]);

  useEffect(() => {
    setCurtain((c) => (c === "cover" ? "reveal" : c));
    const id = setTimeout(() => setCurtain((c) => (c === "reveal" ? "idle" : c)), 700);
    window.scrollTo({ top: 0 });
    return () => clearTimeout(id);
  }, [path, search]);

  // ---- reveal, titles, spotlight targets: re-scanned whenever the page's content changes
  useEffect(() => {
    if (reduced()) return;
    const main = document.querySelector("main.wrap");
    if (!main) return;
    const io = new IntersectionObserver((entries) => {
      entries.filter((e) => e.isIntersecting).forEach((e, i) => {
        const el = e.target as HTMLElement;
        el.style.transitionDelay = `${Math.min(i, 10) * 45}ms`;
        el.classList.add("fx-in");
        io.unobserve(el);
        setTimeout(() => { el.style.transitionDelay = ""; }, 900);
      });
    }, { rootMargin: "0px 0px -30px 0px" });
    const scan = () => {
      main.querySelectorAll<HTMLElement>(REVEAL).forEach((el) => {
        if (el.dataset.fx || el.closest(".reveal, .drawer")) return;
        el.dataset.fx = "1";
        el.classList.add("fx-r");
        io.observe(el);
      });
      main.querySelectorAll<HTMLElement>(TITLES).forEach(scramble);
    };
    scan();
    const mo = new MutationObserver(() => requestAnimationFrame(scan));
    mo.observe(main, { childList: true, subtree: true });
    return () => {
      io.disconnect(); mo.disconnect();
      // anything still waiting must not stay invisible once this observer is gone
      main.querySelectorAll<HTMLElement>(".fx-r:not(.fx-in)").forEach((el) => el.classList.add("fx-in"));
    };
  }, [path, search]);

  // ---- cursor, spotlight, magnetic and scroll progress (one set of listeners for the whole site)
  useEffect(() => {
    const fine = matchMedia("(pointer: fine)").matches && !reduced();
    document.documentElement.classList.toggle("fx-cursor", fine);
    let x = innerWidth / 2, y = innerHeight / 2, rx = x, ry = y, raf = 0;
    let magnet: HTMLElement | null = null;

    const loop = () => {
      rx += (x - rx) * 0.16; ry += (y - ry) * 0.16;
      if (ring.current) ring.current.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
      raf = requestAnimationFrame(loop);
    };
    const onMove = (e: PointerEvent) => {
      x = e.clientX; y = e.clientY;
      if (dot.current) dot.current.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      const t = e.target as HTMLElement;
      const spot = t.closest<HTMLElement>(SPOT);
      if (spot) {
        const r = spot.getBoundingClientRect();
        spot.style.setProperty("--mx", `${x - r.left}px`);
        spot.style.setProperty("--my", `${y - r.top}px`);
      }
      const m = t.closest<HTMLElement>(MAGNET);
      if (magnet && magnet !== m) { magnet.style.transform = ""; magnet = null; }
      if (m && !reduced()) {
        const r = m.getBoundingClientRect();
        m.style.transform = `translate(${(x - r.left - r.width / 2) * 0.22}px, ${(y - r.top - r.height / 2) * 0.3}px)`;
        magnet = m;
      }
      if (ring.current) {
        const card = t.closest(".sc-card, a.hit, .card a.overview");
        const hot = t.closest("a, button, summary, select, [role=tab], label");
        const text = t.closest("input, textarea, [contenteditable]");
        ring.current.dataset.state = text ? "text" : card ? "card" : hot ? "hot" : "";
      }
    };
    const onDown = () => ring.current?.classList.add("down");
    const onUp = () => ring.current?.classList.remove("down");
    const onLeave = () => ring.current?.classList.add("gone");
    const onEnter = () => ring.current?.classList.remove("gone");
    const onScroll = () => {
      const h = document.documentElement.scrollHeight - innerHeight;
      if (bar.current) bar.current.style.transform = `scaleX(${h > 0 ? scrollY / h : 0})`;
    };

    if (fine) {
      raf = requestAnimationFrame(loop);
      addEventListener("pointerdown", onDown);
      addEventListener("pointerup", onUp);
      document.addEventListener("pointerleave", onLeave);
      document.addEventListener("pointerenter", onEnter);
    }
    addEventListener("pointermove", onMove, { passive: true });
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("pointermove", onMove); removeEventListener("scroll", onScroll);
      removeEventListener("pointerdown", onDown); removeEventListener("pointerup", onUp);
      document.removeEventListener("pointerleave", onLeave); document.removeEventListener("pointerenter", onEnter);
    };
  }, []);

  return (
    <>
      <div ref={bar} className="fx-progress" aria-hidden="true" />
      <div ref={dot} className="fx-dot" aria-hidden="true" />
      <div ref={ring} className="fx-ring" aria-hidden="true"><span>Open</span></div>
      <div className={`fx-curtain ${curtain}`} aria-hidden="true">
        <div className="fx-curtain-mark"><Leaf size={42} /></div>
      </div>
    </>
  );
}
