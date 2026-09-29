import type { Line, Page, Part } from "./types";

export function pad(value: number) {
  return String(value).padStart(3, "0");
}

export function newId(prefix: string) {
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${prefix}_${hex}`;
}

export function stripLine(line: Line) {
  return {
    id: line.id,
    box: line.box.slice(0, 4).map((value) => Math.round(Number(value))),
    include: line.include !== false,
    parts: (line.parts || []).map((part) => ({ id: part.id, text: part.text || "" })),
  };
}

export function annotate(lines: Line[]): Line[] {
  const stripped = (lines || []).map(stripLine);
  const columns = readingColumn(stripped);
  const ordered = [...stripped].sort((a, b) => {
    const column = (columns.get(a.id) || 0) - (columns.get(b.id) || 0);
    if (column) return column;
    if (a.box[1] !== b.box[1]) return a.box[1] - b.box[1];
    if (a.box[0] !== b.box[0]) return a.box[0] - b.box[0];
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  let transcript = 0;
  return ordered.map((line, index) => {
    const parts: Part[] = line.parts.map((part, partIndex) => {
      const record: Part = { ...part, parte: partIndex + 1, linha_transcrita: null };
      if (line.include) {
        transcript += 1;
        record.linha_transcrita = transcript;
      }
      return record;
    });
    return { ...line, include: line.include, linha_documento: index + 1, parts };
  });
}

function readingColumn(lines: ReturnType<typeof stripLine>[]) {
  const columns = new Map(lines.map((line) => [line.id, 0]));
  if (lines.length < 4) return columns;
  const ordered = [...lines].sort((a, b) => (a.box[0] + a.box[2]) / 2 - (b.box[0] + b.box[2]) / 2);
  let bestGap = 0;
  let splitAfter = -1;
  for (let index = 0; index < ordered.length - 1; index += 1) {
    const gap = ordered[index + 1].box[0] - ordered[index].box[2];
    const leftCount = index + 1;
    const rightCount = ordered.length - leftCount;
    if (gap >= 40 && leftCount >= 2 && rightCount >= 2 && gap > bestGap) {
      bestGap = gap;
      splitAfter = index;
    }
  }
  if (splitAfter < 0) return columns;
  ordered.forEach((line, index) => columns.set(line.id, index <= splitAfter ? 0 : 1));
  return columns;
}

export function viewMetrics(page: Page, showOriginal: boolean) {
  if (showOriginal && page.original_width) {
    return { width: page.original_width, height: page.original_height };
  }
  return { width: page.width, height: page.height };
}

export function viewOffset(page: Page, showOriginal: boolean) {
  if (!showOriginal) return [0, 0];
  const origin = page.crop_origin || [0, 0];
  return [Number(origin[0]) || 0, Number(origin[1]) || 0];
}

export function toViewBox(page: Page, showOriginal: boolean, box: number[]) {
  const [ox, oy] = viewOffset(page, showOriginal);
  return [box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy];
}

export function clampBox(box: number[], width: number, height: number, minSize = 2) {
  let [x0, y0, x1, y1] = box.map((value) => Math.round(value));
  x0 = Math.max(0, Math.min(width - minSize, x0));
  y0 = Math.max(0, Math.min(height - minSize, y0));
  x1 = Math.max(x0 + minSize, Math.min(width, x1));
  y1 = Math.max(y0 + minSize, Math.min(height, y1));
  return [x0, y0, x1, y1];
}

export function labelFor(line: Line) {
  const doc = `D-${pad(line.linha_documento || 0)}`;
  const numbers = line.parts.map((part) => part.linha_transcrita).filter((value): value is number => Boolean(value));
  if (!line.include || !numbers.length) return `${doc}  sem T`;
  if (numbers.length === 1) return `${doc}  T-${pad(numbers[0])}`;
  return `${doc}  T-${pad(numbers[0])}–${pad(numbers[numbers.length - 1])}`;
}

export function sensText(value: number) {
  if (value < 0.4) return "poucas faixas";
  if (value > 0.7) return "muitas faixas";
  return "faixas médias";
}
