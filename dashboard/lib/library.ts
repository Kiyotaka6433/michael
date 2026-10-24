// Types and calls for the read-only library pages (backend: /api/v1/library, /api/v1/note, /api/v1/search).
import { get } from "./api";

export type Article = {
  title: string; path: string | null; route: string | null; formulas: number | null; rendered: number | null;
  keypoints: string | null; url: string | null;
};
export type LinkRef = { title: string; path: string | null };
export type Topic = {
  name: string; overview: string | null; verified: number | null; total: number | null; deck: string | null;
  articles: Article[]; links: LinkRef[];
};
export type Subject = { name: string; tag: string; intro: string; topics: Topic[]; inbox: LinkRef[] };

export type Note = {
  path: string; title: string; frontmatter: Record<string, string>; markdown: string; backlinks: string[];
  obsidian: string;
};

export type SearchHit = {
  id: string; heading: string; text: string; rel: string; title: string; subject: string; kind: string; score: number;
};

export const noteHref = (path: string, heading?: string) =>
  `/note?path=${encodeURIComponent(path)}${heading ? `#${encodeURIComponent(heading)}` : ""}`;

export const library = () => get<Subject[]>("/api/v1/library");
export const note = (path: string) => get<Note>(`/api/v1/note?path=${encodeURIComponent(path)}`);
export const search = (q: string, subject?: string) =>
  get<{ results: SearchHit[] }>(`/api/v1/search?q=${encodeURIComponent(q)}&k=15${subject ? `&subject=${encodeURIComponent(subject)}` : ""}`);

export type Fact = { fact: string; quote: string; source: string; note: string; score: number };
export const facts = (q: string) => get<{ facts: Fact[] }>(`/api/v1/facts?q=${encodeURIComponent(q)}&k=5`);
