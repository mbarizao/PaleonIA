"use client";

import { Button, Input, Space, Tag } from "antd";
import { useEffect } from "react";
import type { Line, Page } from "@/lib/types";
import { annotate, pad, toViewBox, viewMetrics } from "@/lib/lines";

type Props = {
  page: Page | null;
  showOriginal: boolean;
  selectedLineId: string | null;
  selectedPartId: string | null;
  onSelect: (lineId: string, partId: string | null) => void;
  onText: (partId: string, text: string) => void;
  onSplit: (lineId: string) => void;
  onInclude: (lineId: string, include: boolean) => void;
  onRemovePart: (lineId: string, partId: string) => void;
  onDelete: (lineId: string) => void;
  onNext: () => void;
};

export function LinePanel({
  page,
  showOriginal,
  selectedLineId,
  selectedPartId,
  onSelect,
  onText,
  onSplit,
  onInclude,
  onRemovePart,
  onDelete,
  onNext,
}: Props) {
  const lines = page ? annotate(page.lines) : [];
  const selected = lines.find((line) => line.id === selectedLineId) || null;
  const numbers = selected?.parts.map((part) => part.linha_transcrita).filter((value): value is number => Boolean(value)) || [];
  const transcript =
    numbers.length === 0 ? "—" : numbers.length === 1 ? `T-${pad(numbers[0])}` : `T-${pad(numbers[0])}–${pad(numbers[numbers.length - 1])}`;

  useEffect(() => {
    if (!selectedLineId) return;
    document.getElementById(`line-${selectedLineId}`)?.scrollIntoView({ block: "nearest" });
  }, [selectedLineId]);

  return (
    <aside className="transcript">
      <div className="transcript-head">
        <div>
          <p className="eyebrow">Linha no documento</p>
          <strong>{selected ? `D-${pad(selected.linha_documento || 0)}` : "—"}</strong>
        </div>
        <span className="transcript-link">corresponde a</span>
        <div className="align-end">
          <p className="eyebrow">Linha transcrita</p>
          <strong>{transcript}</strong>
        </div>
      </div>
      {!page || !lines.length ? (
        <p className="page-empty">Nenhuma linha nesta página. Use Nova linha ou Detectar linhas.</p>
      ) : (
        lines.map((line) => (
          <article
            key={line.id}
            id={`line-${line.id}`}
            className={`line-card${line.id === selectedLineId ? " selected" : ""}`}
            onClick={(event) => {
              const target = event.target as HTMLElement;
              if (target.closest("button, textarea")) return;
              onSelect(line.id, line.parts[0]?.id || null);
            }}
          >
            <Space size={6} wrap>
              <Tag color="#0a253e" style={{ margin: 0, fontWeight: 700 }}>
                D-{pad(line.linha_documento || 0)}
              </Tag>
              {line.include && line.parts.some((part) => part.linha_transcrita) ? (
                <Tag style={{ margin: 0, color: "#6b5420", background: "#f6f1e6", borderColor: "#e4d3ae", fontWeight: 700 }}>
                  {transcriptLabel(line)}
                </Tag>
              ) : (
                <Tag style={{ margin: 0 }}>fora da transcrição</Tag>
              )}
            </Space>
            {page ? <Crop page={page} showOriginal={showOriginal} box={line.box} /> : null}
            {line.parts.map((part) => (
              <label key={part.id} style={{ display: "grid", gap: 6, marginTop: 8 }}>
                <span className="page-meta">
                  {part.linha_transcrita ? `Linha transcrita T-${pad(part.linha_transcrita)}` : "Texto guardado, fora da numeração"}
                </span>
                <Input.TextArea
                  rows={2}
                  spellCheck={false}
                  value={part.text || ""}
                  placeholder={`Transcreva a linha D-${pad(line.linha_documento || 0)}`}
                  onFocus={() => onSelect(line.id, part.id)}
                  onChange={(event) => onText(part.id, event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      onSelect(line.id, part.id);
                      onNext();
                    }
                  }}
                  style={part.id === selectedPartId ? { borderColor: "#ab7e32", boxShadow: "0 0 0 2px rgba(171, 126, 50, 0.15)" } : undefined}
                />
                {line.parts.length > 1 ? (
                  <Button type="text" size="small" onClick={() => onRemovePart(line.id, part.id)} style={{ justifySelf: "start" }}>
                    Remover esta linha transcrita
                  </Button>
                ) : null}
              </label>
            ))}
            <Space size={0} wrap style={{ marginTop: 4 }}>
              {line.include ? (
                <>
                  <Button type="text" size="small" onClick={() => onSplit(line.id)}>
                    Dividir
                  </Button>
                  <Button type="text" size="small" onClick={() => onInclude(line.id, false)}>
                    Omitir
                  </Button>
                </>
              ) : (
                <Button type="text" size="small" onClick={() => onInclude(line.id, true)}>
                  Incluir na transcrição
                </Button>
              )}
              <Button type="text" size="small" danger onClick={() => onDelete(line.id)}>
                Excluir faixa
              </Button>
            </Space>
          </article>
        ))
      )}
    </aside>
  );
}

function transcriptLabel(line: Line) {
  const numbers = line.parts.map((part) => part.linha_transcrita).filter((value): value is number => Boolean(value));
  if (numbers.length > 1) return `T-${pad(numbers[0])}–${pad(numbers[numbers.length - 1])}`;
  return `T-${pad(numbers[0])}`;
}

function Crop({ page, showOriginal, box }: { page: Page; showOriginal: boolean; box: number[] }) {
  const url = showOriginal && page.original_url ? page.original_url : page.image_url;
  const { width } = viewMetrics(page, showOriginal);
  const [x0, y0, x1, y1] = toViewBox(page, showOriginal, box);
  const span = Math.max(1, x1 - x0);
  const scale = 300 / span;
  const height = Math.max(28, (y1 - y0) * scale);
  return (
    <div
      className="crop-preview"
      style={{
        height,
        backgroundImage: `url('${url}')`,
        backgroundRepeat: "no-repeat",
        backgroundSize: `${width * scale}px auto`,
        backgroundPosition: `${-x0 * scale}px ${-y0 * scale}px`,
      }}
    />
  );
}
