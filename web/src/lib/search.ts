import { annotate } from "./lines";
import type { Line, Page, Part } from "./types";

const ACCENTS: Record<string, string> = {
  a: "aáàâãä",
  e: "eéèêë",
  i: "iíìîï",
  o: "oóòôõö",
  u: "uúùûü",
  c: "cç",
  n: "nñ",
};

export type TextHit = {
  page: Page;
  line: Line;
  part: Part;
};

export function fold(value: string) {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

export function textHits(pages: Page[], query: string): TextHit[] {
  const foldedQuery = fold(query.trim());
  if (foldedQuery.length < 2) return [];
  const words = foldedQuery.split(/\s+/).filter((word) => word.length >= 2);
  const hits: TextHit[] = [];
  for (const page of pages) {
    for (const line of annotate(page.lines)) {
      for (const part of line.parts) {
        const text = (part.text || "").trim();
        if (!text) continue;
        const folded = fold(text);
        const phrase = folded.includes(foldedQuery);
        const everyWord = words.length > 1 && words.every((word) => folded.includes(word));
        if (phrase || everyWord) hits.push({ page, line, part });
      }
    }
  }
  return hits;
}

export function nameMatches(pages: Page[], query: string) {
  const folded = fold(query.trim());
  if (!folded) return pages;
  return pages.filter((page) => fold(page.filename).includes(folded));
}

export function highlightParts(text: string, query: string) {
  const words = fold(query.trim())
    .split(/\s+/)
    .filter((word) => word.length >= 2);
  if (!words.length) return [{ text, hit: false }];
  const pattern = words.map(wordPattern).join("|");
  const expression = new RegExp(pattern, "giu");
  const parts: { text: string; hit: boolean }[] = [];
  let last = 0;
  for (const match of text.matchAll(expression)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start), hit: false });
    if (match[0]) parts.push({ text: match[0], hit: true });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), hit: false });
  return parts.length ? parts : [{ text, hit: false }];
}

export function passageSnippet(text: string, query: string) {
  if (text.length <= 180) return text;
  const parts = highlightParts(text, query);
  const index = parts.findIndex((part) => part.hit);
  if (index < 0) return `${text.slice(0, 180).trim()}…`;
  const before = parts.slice(0, index).reduce((sum, part) => sum + part.text.length, 0);
  const start = Math.max(0, before - 56);
  const end = Math.min(text.length, start + 180);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < text.length ? "…" : "";
  return `${prefix}${text.slice(start, end).trim()}${suffix}`;
}

function wordPattern(word: string) {
  return [...word]
    .map((char) => {
      const group = ACCENTS[char];
      if (group) return `[${group}]`;
      return char.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("");
}
