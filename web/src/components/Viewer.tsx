"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { Line, Page } from "@/lib/types";
import { annotate, clampBox, labelFor, newId, toViewBox, viewMetrics } from "@/lib/lines";

const MIN_ZOOM = 0.05;
const MAX_ZOOM = 40;

type Drag =
  | { kind: "pan"; x: number; y: number; moved: boolean }
  | { kind: "move"; origin: number[]; lineId: string; start: { x: number; y: number }; moved: boolean }
  | { kind: "top" | "bottom"; origin: number[]; lineId: string; moved: boolean }
  | { kind: "draw"; start: { x: number; y: number }; draft: number[] | null; moved: boolean };

export type ViewerHandle = {
  zoomBy: (factor: number) => void;
  fit: () => void;
  actual: () => void;
};

type Props = {
  page: Page;
  showOriginal: boolean;
  selectedLineId: string | null;
  tool: "select" | "draw";
  onSelect: (lineId: string | null, partId: string | null) => void;
  onLines: (lines: Line[]) => void;
};

export const Viewer = forwardRef<ViewerHandle, Props>(function Viewer(
  { page, showOriginal, selectedLineId, tool, onSelect, onLines },
  ref,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const view = useRef({ zoom: 1, panX: 0, panY: 0 });
  const drag = useRef<Drag | null>(null);
  const space = useRef(false);
  const pageRef = useRef(page);
  const toolRef = useRef(tool);
  const selectedRef = useRef(selectedLineId);
  const showRef = useRef(showOriginal);
  pageRef.current = page;
  toolRef.current = tool;
  selectedRef.current = selectedLineId;
  showRef.current = showOriginal;

  function imageUrl() {
    if (showOriginal && page.original_url) return page.original_url;
    return page.image_url;
  }

  function applyTransform() {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const { zoom, panX, panY } = view.current;
    wrap.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  }

  function draw() {
    const canvas = canvasRef.current;
    const current = pageRef.current;
    if (!canvas || !current) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const metrics = viewMetrics(current, showRef.current);
    canvas.width = metrics.width;
    canvas.height = metrics.height;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const zoom = view.current.zoom;
    const stroke = Math.max(1, 1.4 / zoom);
    const lines = annotate(current.lines);
    for (const line of lines) {
      const [x0, y0, x1, y1] = toViewBox(current, showRef.current, line.box);
      const selected = line.id === selectedRef.current;
      ctx.setLineDash(line.include ? [] : [8 / zoom, 5 / zoom]);
      ctx.fillStyle = selected
        ? "rgba(171, 126, 50, 0.34)"
        : line.include
          ? "rgba(213, 230, 245, 0.16)"
          : "rgba(183, 198, 214, 0.1)";
      ctx.strokeStyle = selected ? "#ab7e32" : line.include ? "rgba(213, 230, 245, 0.92)" : "rgba(183, 198, 214, 0.7)";
      ctx.lineWidth = selected ? stroke * 1.8 : stroke;
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      if (selected || zoom >= 0.34) drawLabel(ctx, x0, y0, labelFor(line), selected, zoom);
    }
    ctx.setLineDash([]);
    const draft = drag.current?.kind === "draw" ? drag.current.draft : null;
    if (draft) {
      const [x0, y0, x1, y1] = toViewBox(current, showRef.current, draft);
      ctx.strokeStyle = "#ab7e32";
      ctx.lineWidth = stroke * 1.6;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
  }

  function fit() {
    const scroll = scrollRef.current;
    const current = pageRef.current;
    if (!scroll || !current) return;
    const metrics = viewMetrics(current, showRef.current);
    const zoom = Math.min(scroll.clientWidth / metrics.width, scroll.clientHeight / metrics.height);
    view.current.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
    view.current.panX = (scroll.clientWidth - metrics.width * view.current.zoom) / 2;
    view.current.panY = (scroll.clientHeight - metrics.height * view.current.zoom) / 2;
    applyTransform();
    draw();
  }

  function zoomAt(clientX: number, clientY: number, factor: number) {
    const scroll = scrollRef.current;
    if (!scroll) return;
    const rect = scroll.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    const { zoom, panX, panY } = view.current;
    const pageX = (mx - panX) / zoom;
    const pageY = (my - panY) / zoom;
    view.current.zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
    view.current.panX = mx - pageX * view.current.zoom;
    view.current.panY = my - pageY * view.current.zoom;
    applyTransform();
    draw();
  }

  useImperativeHandle(ref, () => ({
    zoomBy(factor: number) {
      const scroll = scrollRef.current;
      if (!scroll) return;
      const rect = scroll.getBoundingClientRect();
      zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
    },
    fit,
    actual() {
      const scroll = scrollRef.current;
      const current = pageRef.current;
      if (!scroll || !current) return;
      const rect = scroll.getBoundingClientRect();
      const mx = rect.width / 2;
      const my = rect.height / 2;
      const { zoom, panX, panY } = view.current;
      const pageX = (mx - panX) / zoom;
      const pageY = (my - panY) / zoom;
      view.current.zoom = 1;
      view.current.panX = mx - pageX;
      view.current.panY = my - pageY;
      applyTransform();
      draw();
    },
  }));

  useEffect(() => {
    draw();
  }, [page, showOriginal, selectedLineId, tool]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      zoomAt(event.clientX, event.clientY, Math.exp(-event.deltaY * 0.0015));
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
      if (event.code === "Space") {
        event.preventDefault();
        space.current = event.type === "keydown";
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
    };
  }, []);

  function toStored(clientX: number, clientY: number) {
    const scroll = scrollRef.current!;
    const rect = scroll.getBoundingClientRect();
    const { zoom, panX, panY } = view.current;
    const x = (clientX - rect.left - panX) / zoom;
    const y = (clientY - rect.top - panY) / zoom;
    const current = pageRef.current;
    const origin = showRef.current ? current.crop_origin || [0, 0] : [0, 0];
    return { x: x - Number(origin[0] || 0), y: y - Number(origin[1] || 0) };
  }

  function hitEdge(x: number, y: number) {
    const slack = 8 / view.current.zoom;
    let best: { line: Line; edge: "top" | "bottom" } | null = null;
    let bestDist = slack;
    for (const line of pageRef.current.lines) {
      const [x0, y0, x1, y1] = line.box;
      if (x < x0 - slack || x > x1 + slack) continue;
      for (const [edge, ey] of [
        ["top", y0],
        ["bottom", y1],
      ] as const) {
        const dist = Math.abs(y - ey);
        if (dist <= bestDist) {
          bestDist = dist;
          best = { line, edge };
        }
      }
    }
    return best;
  }

  function hitTest(x: number, y: number) {
    let best: Line | null = null;
    let bestArea = Infinity;
    for (const line of pageRef.current.lines) {
      const [x0, y0, x1, y1] = line.box;
      if (x >= x0 && x <= x1 && y >= y0 && y <= y1) {
        const area = (x1 - x0) * (y1 - y0);
        if (area < bestArea) {
          best = line;
          bestArea = area;
        }
      }
    }
    return best;
  }

  function replaceLine(lineId: string, box: number[]) {
    onLines(pageRef.current.lines.map((line) => (line.id === lineId ? { ...line, box } : line)));
  }

  return (
    <div
      ref={scrollRef}
      className={`viewer-scroll${tool === "draw" ? " drawing" : ""}`}
      onPointerDown={(event) => {
        if (event.button !== 0 && event.button !== 1) return;
        const point = toStored(event.clientX, event.clientY);
        const panMode = event.button === 1 || event.altKey || event.shiftKey || space.current;
        const edge = !panMode && toolRef.current === "select" ? hitEdge(point.x, point.y) : null;
        const hit = !panMode && !edge && toolRef.current === "select" ? hitTest(point.x, point.y) : null;
        if (edge) {
          onSelect(edge.line.id, edge.line.parts[0]?.id || null);
          drag.current = { kind: edge.edge, origin: [...edge.line.box], lineId: edge.line.id, moved: false };
        } else if (hit) {
          onSelect(hit.id, hit.parts[0]?.id || null);
          drag.current = { kind: "move", origin: [...hit.box], lineId: hit.id, start: point, moved: false };
        } else if (!panMode && toolRef.current === "draw") {
          drag.current = { kind: "draw", start: point, draft: null, moved: false };
        } else {
          drag.current = { kind: "pan", x: event.clientX, y: event.clientY, moved: false };
          scrollRef.current?.classList.add("panning");
        }
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const point = toStored(event.clientX, event.clientY);
        const currentDrag = drag.current;
        if (!currentDrag) {
          const edge = toolRef.current === "select" ? hitEdge(point.x, point.y) : null;
          if (scrollRef.current) {
            scrollRef.current.style.cursor = edge ? "ns-resize" : toolRef.current === "draw" ? "crosshair" : "grab";
          }
          return;
        }
        if (currentDrag.kind === "pan") {
          view.current.panX += event.clientX - currentDrag.x;
          view.current.panY += event.clientY - currentDrag.y;
          currentDrag.x = event.clientX;
          currentDrag.y = event.clientY;
          currentDrag.moved = true;
          applyTransform();
          return;
        }
        const current = pageRef.current;
        if (currentDrag.kind === "move") {
          const dx = point.x - currentDrag.start.x;
          const dy = point.y - currentDrag.start.y;
          const origin = currentDrag.origin;
          const boxW = origin[2] - origin[0];
          const boxH = origin[3] - origin[1];
          const x0 = Math.max(0, Math.min(current.width - boxW, origin[0] + dx));
          const y0 = Math.max(0, Math.min(current.height - boxH, origin[1] + dy));
          replaceLine(currentDrag.lineId, [Math.round(x0), Math.round(y0), Math.round(x0 + boxW), Math.round(y0 + boxH)]);
          currentDrag.moved = true;
        } else if (currentDrag.kind === "top" || currentDrag.kind === "bottom") {
          const next = [...currentDrag.origin];
          if (currentDrag.kind === "top") next[1] = Math.min(point.y, currentDrag.origin[3] - 8);
          else next[3] = Math.max(point.y, currentDrag.origin[1] + 8);
          replaceLine(currentDrag.lineId, clampBox(next, current.width, current.height, 8));
          currentDrag.moved = true;
        } else if (currentDrag.kind === "draw") {
          let x0 = Math.min(currentDrag.start.x, point.x);
          let x1 = Math.max(currentDrag.start.x, point.x);
          const y0 = Math.min(currentDrag.start.y, point.y);
          const y1 = Math.max(currentDrag.start.y, point.y);
          if (x1 - x0 < current.width * 0.12) {
            x0 = current.width * 0.02;
            x1 = current.width * 0.98;
          }
          currentDrag.draft = [x0, y0, x1, y1];
          currentDrag.moved = Math.abs(point.y - currentDrag.start.y) > 4;
          draw();
        }
      }}
      onPointerUp={() => {
        const currentDrag = drag.current;
        drag.current = null;
        scrollRef.current?.classList.remove("panning");
        if (!currentDrag || !currentDrag.moved) return;
        if (currentDrag.kind === "draw" && currentDrag.draft) {
          const box = clampBox(currentDrag.draft, pageRef.current.width, pageRef.current.height, 8);
          const line: Line = {
            id: newId("ln"),
            box,
            include: true,
            parts: [{ id: newId("pt"), text: "" }],
          };
          onLines([...pageRef.current.lines, line]);
          onSelect(line.id, line.parts[0].id);
        }
      }}
    >
      <div ref={wrapRef} className="canvas-wrap">
        <img
          src={imageUrl()}
          alt={page.filename}
          draggable={false}
          onLoad={() => {
            const metrics = viewMetrics(page, showOriginal);
            if (wrapRef.current) {
              wrapRef.current.style.width = `${metrics.width}px`;
              wrapRef.current.style.height = `${metrics.height}px`;
            }
            fit();
          }}
        />
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
});

function drawLabel(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  text: string,
  selected: boolean,
  zoom: number,
) {
  const size = Math.max(11, 14 / zoom);
  ctx.font = `700 ${size}px Segoe UI, sans-serif`;
  const padX = 5 / zoom;
  const padY = 3 / zoom;
  const width = ctx.measureText(text).width + padX * 2;
  const height = size + padY * 2;
  const top = Math.max(0, y - height);
  ctx.fillStyle = "rgba(10, 37, 62, 0.92)";
  ctx.fillRect(x, top, width, height);
  ctx.fillStyle = selected ? "#f7fbff" : "#f6edd6";
  ctx.fillText(text, x + padX, top + height - padY * 1.7);
}
