"use client";
// The hero background: a drifting "root network" - nodes linked when close, and drawn toward the cursor, which
// grows roots to everything near it. Canvas 2D, DPR-aware, paused off-screen and for reduced motion.
import { useEffect, useRef } from "react";

type P = { x: number; y: number; vx: number; vy: number; r: number };

export default function HeroCanvas() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const c = canvas.current!;
    const ctx = c.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, dpr = 1, raf = 0, visible = true;
    let pts: P[] = [];
    const mouse = { x: -9999, y: -9999, on: false };
    let accent = "16,185,129";

    const readAccent = () => {
      const v = getComputedStyle(document.documentElement).getPropertyValue("--accent-rgb").trim();
      if (v) accent = v;
    };
    const resize = () => {
      const r = c.getBoundingClientRect();
      dpr = Math.min(2, devicePixelRatio || 1);
      w = r.width; h = r.height;
      c.width = w * dpr; c.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.round(Math.min(110, (w * h) / 11000));
      pts = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.28, vy: (Math.random() - 0.5) * 0.28, r: 1 + Math.random() * 1.6,
      }));
    };

    const LINK = 118, PULL = 190;
    const frame = () => {
      ctx.clearRect(0, 0, w, h);
      for (const p of pts) {
        if (mouse.on) {                                   // gentle pull toward the cursor
          const dx = mouse.x - p.x, dy = mouse.y - p.y, d = Math.hypot(dx, dy);
          if (d < PULL && d > 1) { p.vx += (dx / d) * 0.012; p.vy += (dy / d) * 0.012; }
        }
        p.vx *= 0.985; p.vy *= 0.985;
        p.vx += (Math.random() - 0.5) * 0.02; p.vy += (Math.random() - 0.5) * 0.02;
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > w) p.vx *= -1;
        if (p.y < 0 || p.y > h) p.vy *= -1;
      }
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        for (let j = i + 1; j < pts.length; j++) {
          const b = pts[j], d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < LINK) {
            ctx.strokeStyle = `rgba(${accent},${0.16 * (1 - d / LINK)})`;
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
        if (mouse.on) {
          const d = Math.hypot(a.x - mouse.x, a.y - mouse.y);
          if (d < PULL) {
            ctx.strokeStyle = `rgba(${accent},${0.45 * (1 - d / PULL)})`;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke();
          }
        }
        ctx.fillStyle = `rgba(${accent},0.75)`;
        ctx.beginPath(); ctx.arc(a.x, a.y, a.r, 0, Math.PI * 2); ctx.fill();
      }
      if (visible && !still) raf = requestAnimationFrame(frame);
    };

    const onMove = (e: PointerEvent) => {
      const r = c.getBoundingClientRect();
      mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
      mouse.on = mouse.y >= 0 && mouse.y <= r.height;
      c.parentElement?.style.setProperty("--gx", `${mouse.x}px`);
      c.parentElement?.style.setProperty("--gy", `${mouse.y}px`);
    };
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      cancelAnimationFrame(raf);
      if (visible) raf = requestAnimationFrame(frame);
    });
    const mo = new MutationObserver(readAccent);

    readAccent(); resize(); frame();
    io.observe(c);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    addEventListener("resize", resize);
    addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelAnimationFrame(raf); io.disconnect(); mo.disconnect();
      removeEventListener("resize", resize); removeEventListener("pointermove", onMove);
    };
  }, []);

  return <canvas ref={canvas} className="hero-canvas" aria-hidden="true" />;
}
