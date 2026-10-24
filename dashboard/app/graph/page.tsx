"use client";
// The library as a graph in the browser: the same notes and links as Obsidian's graph view, coloured the same way.
import { useEffect, useRef, useState } from "react";
import { API } from "../../lib/api";
import { noteHref } from "../../lib/library";

type G = { nodes: { id: string; label: string; subject: string; kind: string }[]; edges: { source: string; target: string }[] };

const SUBJECT: Record<string, string> = {
  "Number Theory": "#c49a6c", "DSA and Competitive Programming": "#7fb069", "Machine Learning": "#e0c068",
};
const color = (n: G["nodes"][number]) =>
  n.kind === "hub" ? "#f2e8c9" : n.kind === "topic" ? "#4f9d69" : n.kind === "keypoints" ? "#8a8f78" : SUBJECT[n.subject] ?? "#9aa0a6";

export default function GraphPage() {
  const box = useRef<HTMLDivElement>(null);
  const [info, setInfo] = useState("Loading…");

  useEffect(() => {
    let cy: any;
    (async () => {
      const [{ default: cytoscape }, g] = await Promise.all([
        import("cytoscape"), fetch(`${API}/api/v1/graph`).then((r) => r.json() as Promise<G>),
      ]);
      const degree: Record<string, number> = {};
      g.edges.forEach((e) => { degree[e.source] = (degree[e.source] ?? 0) + 1; degree[e.target] = (degree[e.target] ?? 0) + 1; });
      cy = cytoscape({
        container: box.current,
        elements: [
          ...g.nodes.map((n) => ({ data: { id: n.id, label: n.label, color: color(n), size: 6 + Math.sqrt(degree[n.id] ?? 0) * 3 } })),
          ...g.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target } })),
        ],
        style: [
          { selector: "node", style: { "background-color": "data(color)", width: "data(size)", height: "data(size)",
              label: "data(label)", "font-size": 6, color: "#d9d4bf", "text-valign": "bottom", "text-margin-y": 2,
              "min-zoomed-font-size": 9 } },
          { selector: "edge", style: { width: 0.4, "line-color": "#5b6b4a", opacity: 0.55 } },
          { selector: ".faded", style: { opacity: 0.12 } },
        ],
        layout: { name: "cose", animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 60, numIter: 1500 },
        wheelSensitivity: 0.2,
      });
      cy.on("mouseover", "node", (ev: any) => {
        const n = ev.target;
        cy.elements().addClass("faded");
        n.closedNeighborhood().removeClass("faded");
      });
      cy.on("mouseout", "node", () => cy.elements().removeClass("faded"));
      cy.on("tap", "node", (ev: any) => { window.location.href = noteHref(ev.target.id()); });
      setInfo(`${g.nodes.length} notes · ${g.edges.length} links · hover to focus, click to open`);
    })().catch(() => setInfo("Michael's backend is not running."));
    return () => cy?.destroy();
  }, []);

  return (
    <>
      <div className="row between">
        <h1 className="page-title">Graph</h1>
        <span className="muted small">{info}</span>
      </div>
      <div className="legend muted small">
        <span style={{ color: "#c9b98a" }}>● hubs</span> <span style={{ color: "#4f9d69" }}>● topic overviews</span>{" "}
        <span style={{ color: "#a77a4c" }}>● Number Theory</span> <span style={{ color: "#6b8f47" }}>● DSA</span>{" "}
        <span style={{ color: "#b8913f" }}>● Machine Learning</span> <span style={{ color: "#8a8f78" }}>● key points</span>
      </div>
      <div ref={box} className="graph-box" />
    </>
  );
}
