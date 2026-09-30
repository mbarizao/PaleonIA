"use client";

import { Button, Input } from "antd";
import { useState } from "react";
import { draftParts, pad, toViewBox, viewMetrics } from "@/lib/lines";
import type { Line, Page } from "@/lib/types";

type Props = {
  pages: Page[];
  onCommit: (page: Page, lineId: string, partId: string, text: string, mark: "confirmed" | "skipped") => void;
  onOpen: (page: Page, lineId: string, partId: string) => void;
};

export function Corrections({ pages, onCommit, onOpen }: Props) {
  const items = draftParts(pages);
  const [cursor, setCursor] = useState<string | null>(null);
  const [editing, setEditing] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const found = items.findIndex((item) => item.part.id === cursor);
  const index = found >= 0 ? found : 0;
  const current = items[index] || null;

  function goNext() {
    const next = items[index + 1] || items[index - 1];
    setCursor(next?.part.id ?? null);
    setEditOpen(false);
  }

  function commit(mark: "confirmed" | "skipped", text: string) {
    if (!current) return;
    goNext();
    onCommit(current.page, current.line.id, current.part.id, text, mark);
  }

  if (!current) {
    return (
      <section className="review">
        <header className="review-head">
          <p className="eyebrow">Correções</p>
          <h1>Linhas em rascunho</h1>
        </header>
        <div className="review-empty">
          <p>Não há linhas em rascunho. O texto conferido passa a servir de precedente na leitura seguinte.</p>
        </div>
      </section>
    );
  }

  const label = transcriptLabel(current.line);
  const pageItems = items.filter((item) => item.page.id === current.page.id);
  const pageIndex = pageItems.findIndex((item) => item.part.id === current.part.id);

  return (
    <section className="review">
      <header className="review-head">
        <p className="eyebrow">Correções</p>
        <h1>Linhas em rascunho</h1>
        <p>
          {index + 1} de {items.length}, em todas as páginas. Correto entra no acervo. Ilegível fica de fora da próxima leitura.
        </p>
      </header>
      <article className="review-card">
        <div className="review-page">
          <span className="review-page-thumb">
            <img src={current.page.thumb_url || current.page.image_url} alt="" />
          </span>
          <div className="review-page-copy">
            <p className="eyebrow">Página</p>
            <strong>{current.page.filename}</strong>
            <p>
              {pageIndex + 1} de {pageItems.length} {pageItems.length === 1 ? "rascunho nesta página" : "rascunhos nesta página"}
            </p>
          </div>
        </div>
        <div className="review-meta">
          <span>D-{pad(current.line.linha_documento || 0)}</span>
          <span>{label}</span>
        </div>
        <Crop page={current.page} box={current.line.box} />
        {editOpen ? (
          <Input.TextArea
            rows={3}
            spellCheck={false}
            value={editing}
            autoFocus
            onChange={(event) => setEditing(event.target.value)}
          />
        ) : (
          <p className="review-text">{current.part.text}</p>
        )}
        <div className="review-actions">
          {editOpen ? (
            <>
              <Button onClick={() => setEditOpen(false)}>Cancelar</Button>
              <Button type="primary" disabled={!editing.trim()} onClick={() => commit("confirmed", editing)}>
                Guardar correção
              </Button>
            </>
          ) : (
            <>
              <Button type="primary" onClick={() => commit("confirmed", current.part.text)}>
                Correto
              </Button>
              <Button
                onClick={() => {
                  setEditing(current.part.text);
                  setEditOpen(true);
                }}
              >
                Corrigir
              </Button>
              <Button onClick={() => commit("skipped", current.part.text)}>Ilegível</Button>
              <Button type="link" onClick={() => onOpen(current.page, current.line.id, current.part.id)}>
                Abrir na mesa
              </Button>
            </>
          )}
        </div>
      </article>
    </section>
  );
}

function transcriptLabel(line: Line) {
  const numbers = line.parts.map((part) => part.linha_transcrita).filter((value): value is number => Boolean(value));
  if (!numbers.length) return "sem T";
  if (numbers.length > 1) return `T-${pad(numbers[0])}–${pad(numbers[numbers.length - 1])}`;
  return `T-${pad(numbers[0])}`;
}

function Crop({ page, box }: { page: Page; box: number[] }) {
  const { width } = viewMetrics(page, false);
  const [x0, y0, x1, y1] = toViewBox(page, false, box);
  const span = Math.max(1, x1 - x0);
  const scale = 640 / span;
  const height = Math.max(48, Math.min(180, (y1 - y0) * scale));
  return (
    <div
      className="review-crop"
      style={{
        height,
        backgroundImage: `url('${page.image_url}')`,
        backgroundRepeat: "no-repeat",
        backgroundSize: `${width * scale}px auto`,
        backgroundPosition: `${-x0 * scale}px ${-y0 * scale}px`,
      }}
    />
  );
}
