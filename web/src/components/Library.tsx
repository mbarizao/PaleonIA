"use client";

import { DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import { Button, Input, Segmented } from "antd";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { annotate, labelFor, pad } from "@/lib/lines";
import { highlightParts, nameMatches, passageSnippet, textHits, type TextHit } from "@/lib/search";
import type { Page, SearchHit, SearchResponse } from "@/lib/types";

const HIT_CAP = 80;

type Scope = "todos" | "texto" | "vazio";

type Props = {
  pages: Page[];
  vectorSearch: boolean;
  onOpen: (page: Page, focus?: { lineId: string; partId: string | null }) => void;
  onRemove: (page: Page) => void;
  importAction: ReactNode;
};

export function Library({ pages, vectorSearch, onOpen, onRemove, importAction }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<Scope>("todos");
  const [similar, setSimilar] = useState<SearchHit[]>([]);
  const [similarReady, setSimilarReady] = useState(true);
  const trimmed = query.trim();
  const searching = trimmed.length >= 2;
  const catalog = useMemo(() => pages.map((page) => ({ page, ...pageStats(page) })), [pages]);
  const totals = useMemo(
    () =>
      catalog.reduce(
        (sum, item) => ({
          lines: sum.lines + item.lines,
          written: sum.written + item.written,
        }),
        { lines: 0, written: 0 },
      ),
    [catalog],
  );
  const hits = useMemo(() => textHits(pages, trimmed), [pages, trimmed]);
  const shown = hits.slice(0, HIT_CAP);
  const byName = useMemo(() => {
    const named = new Set((trimmed ? nameMatches(pages, trimmed) : pages).map((page) => page.id));
    return catalog.filter((item) => named.has(item.page.id) && (searching || inScope(item, scope)));
  }, [catalog, pages, scope, searching, trimmed]);
  const hitPageIds = useMemo(() => new Set(hits.map((hit) => hit.page.id)), [hits]);
  const nameOnly = byName.filter((item) => !hitPageIds.has(item.page.id));
  const groups = useMemo(() => groupHits(shown), [shown]);
  const literalIds = useMemo(() => new Set(hits.map((hit) => hit.part.id)), [hits]);
  const extra = similar.filter((hit) => !literalIds.has(hit.part_id));

  useEffect(() => {
    if (!vectorSearch || !searching) {
      setSimilar([]);
      setSimilarReady(true);
      return;
    }
    setSimilarReady(false);
    const timer = window.setTimeout(() => {
      void api<SearchResponse>(`/api/search?q=${encodeURIComponent(trimmed)}&limit=12`)
        .then((data) => setSimilar(data.enabled ? data.results : []))
        .catch(() => setSimilar([]))
        .finally(() => setSimilarReady(true));
    }, 320);
    return () => window.clearTimeout(timer);
  }, [trimmed, searching, vectorSearch]);

  const visibleCards = searching ? [] : byName;

  return (
    <section className="library">
      <header className="library-bar">
        <div className="library-bar-inner">
          <div className="library-title">
            <p className="eyebrow">Acervo</p>
            <h1>Documentos</h1>
          </div>
          <p className="library-stats">
            {pages.length
              ? `${countLabel(pages.length)} · ${totals.written} de ${totals.lines} linhas com texto`
              : "Importe uma imagem para começar."}
          </p>
          {pages.length ? (
            <div className="library-tools">
              <Input
                allowClear
                size="large"
                prefix={<SearchOutlined />}
                placeholder="Buscar no texto ou no nome"
                value={query}
                aria-label="Buscar no texto ou no nome"
                onChange={(event) => setQuery(event.target.value)}
              />
              {searching ? null : (
                <Segmented
                  value={scope}
                  onChange={(value) => setScope(value as Scope)}
                  options={[
                    { label: "Todos", value: "todos" },
                    { label: "Com texto", value: "texto" },
                    { label: "Sem texto", value: "vazio" },
                  ]}
                />
              )}
            </div>
          ) : null}
          {trimmed.length === 1 ? <p className="library-hint">Mais uma letra para buscar dentro do texto.</p> : null}
        </div>
      </header>

      <div className="library-wrap">
        {!pages.length ? (
          <div className="library-empty-wrap">
            <div className="empty-card library-empty">
              <img className="logo-on-light" src="/brand/PaleonIA-logo.svg" alt="" />
              <img className="logo-on-dark" src="/brand/PaleonIA-logo-white.svg" alt="" />
              <h2>Nenhum documento ainda</h2>
              <p>JPG, PNG, TIFF ou WEBP. Também pode soltar os arquivos nesta janela.</p>
              {importAction}
            </div>
          </div>
        ) : null}

        {visibleCards.length ? (
          <div className="doc-grid">
            {visibleCards.map((item) => (
              <DocumentCard key={item.page.id} item={item} onOpen={onOpen} onRemove={onRemove} />
            ))}
          </div>
        ) : null}

        {pages.length && !searching && !visibleCards.length ? (
          <div className="library-blank">
            <p>{trimmed ? "Nenhum documento com esse nome." : "Nenhum documento nesse filtro."}</p>
          </div>
        ) : null}

        {searching ? (
          <div className="library-results" aria-live="polite">
            {similarReady && !hits.length && !extra.length ? (
              <div className="library-blank">
                <p>Nenhuma passagem com “{trimmed}”.</p>
              </div>
            ) : null}

            {hits.length ? (
              <div className="hit-list">
                <h2 className="library-section">
                  No texto
                  <span>
                    {hits.length === 1 ? "1 passagem" : `${hits.length} passagens`}
                    {hits.length > shown.length ? ` · ${shown.length} primeiras` : ""}
                  </span>
                </h2>
                {groups.map((group) => (
                  <section key={group.page.id} className="hit-group">
                    <button type="button" className="hit-doc" onClick={() => onOpen(group.page)}>
                      <span className="doc-mini">
                        <img src={group.page.thumb_url || group.page.image_url} alt="" />
                      </span>
                      <span className="hit-doc-copy">
                        <strong>{group.page.filename}</strong>
                        <span>{group.hits.length === 1 ? "1 passagem" : `${group.hits.length} passagens`}</span>
                      </span>
                      <span className="hit-open">Abrir</span>
                    </button>
                    {group.hits.map((hit) => (
                      <button
                        key={hit.part.id}
                        type="button"
                        className="hit-passage"
                        onClick={() => onOpen(hit.page, { lineId: hit.line.id, partId: hit.part.id })}
                      >
                        <span className="hit-label">{labelFor(hit.line)}</span>
                        <MarkedText text={passageSnippet(hit.part.text || "", trimmed)} query={trimmed} />
                      </button>
                    ))}
                  </section>
                ))}
              </div>
            ) : null}

            {extra.length ? (
              <div className="hit-list">
                <h2 className="library-section">
                  Parecidas pelo sentido
                  <span>{extra.length === 1 ? "1 passagem" : `${extra.length} passagens`}</span>
                </h2>
                <section className="hit-group">
                  {extra.map((hit) => {
                    const page = pages.find((item) => item.id === hit.page_id);
                    if (!page) return null;
                    return (
                      <button
                        key={`${hit.page_id}-${hit.part_id}`}
                        type="button"
                        className="hit-passage similar"
                        onClick={() => onOpen(page, { lineId: hit.line_id, partId: hit.part_id })}
                      >
                        <span className="hit-label">
                          {hit.linha_documento ? `D-${pad(hit.linha_documento)}` : "Linha"}
                          {hit.linha_transcrita ? `  T-${pad(hit.linha_transcrita)}` : ""}
                          <span>{Math.round(hit.score * 100)}%</span>
                        </span>
                        <span className="hit-text">
                          <span className="hit-file">{hit.filename}</span>
                          {hit.text}
                        </span>
                      </button>
                    );
                  })}
                </section>
              </div>
            ) : null}

            {nameOnly.length ? (
              <div className="hit-list">
                <h2 className="library-section">
                  Pelo nome
                  <span>{nameOnly.length === 1 ? "1 documento" : `${nameOnly.length} documentos`}</span>
                </h2>
                <div className="doc-grid">
                  {nameOnly.map((item) => (
                    <DocumentCard key={item.page.id} item={item} onOpen={onOpen} onRemove={onRemove} />
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function MarkedText({ text, query }: { text: string; query: string }) {
  return (
    <span className="hit-text">
      {highlightParts(text, query).map((part, index) =>
        part.hit ? (
          <mark key={index} className="passage-mark">
            {part.text}
          </mark>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </span>
  );
}

type CardItem = ReturnType<typeof pageStats> & { page: Page };

function DocumentCard({
  item,
  onOpen,
  onRemove,
}: {
  item: CardItem;
  onOpen: (page: Page) => void;
  onRemove: (page: Page) => void;
}) {
  const { page, lines, written } = item;
  const ratio = lines ? Math.round((written / lines) * 100) : 0;

  return (
    <article className="doc-card">
      <button type="button" className="doc-card-open" onClick={() => onOpen(page)}>
        <span className="doc-card-thumb">
          <img src={page.thumb_url || page.image_url} alt="" />
        </span>
        <span className="doc-card-copy">
          <strong title={page.filename}>{page.filename}</strong>
          <span className="doc-progress" aria-hidden="true">
            <span style={{ width: `${ratio}%` }} />
          </span>
          <span className="page-meta">{statusLabel(item)}</span>
          <span className="doc-preview">{item.preview || "Ainda sem texto transcrito."}</span>
        </span>
      </button>
      <Button
        className="doc-card-remove"
        type="text"
        size="small"
        icon={<DeleteOutlined />}
        aria-label={`Remover ${page.filename}`}
        onClick={(event) => {
          event.stopPropagation();
          onRemove(page);
        }}
      />
    </article>
  );
}

function pageStats(page: Page) {
  const lines = annotate(page.lines);
  let written = 0;
  let confirmed = 0;
  const bits: string[] = [];
  for (const line of lines) {
    const texts = line.parts.map((part) => (part.text || "").trim()).filter(Boolean);
    if (!texts.length) continue;
    written += 1;
    if (line.parts.every((part) => !(part.text || "").trim() || part.confirmed)) confirmed += 1;
    if (bits.length < 2) bits.push(texts[0]);
  }
  return { lines: lines.length, written, confirmed, preview: bits.join(" ") };
}

function inScope(item: ReturnType<typeof pageStats>, scope: Scope) {
  if (scope === "texto") return item.written > 0;
  if (scope === "vazio") return item.written === 0;
  return true;
}

function statusLabel(item: ReturnType<typeof pageStats>) {
  if (!item.lines) return "Sem linhas";
  if (!item.written) return `0 de ${item.lines} linhas`;
  if (!item.confirmed) return `${item.written} de ${item.lines} linhas`;
  if (item.confirmed === item.written) return `${item.written} de ${item.lines} linhas conferidas`;
  return `${item.written} de ${item.lines} linhas · ${item.confirmed} conferidas`;
}

function groupHits(hits: TextHit[]) {
  const groups: { page: Page; hits: TextHit[] }[] = [];
  for (const hit of hits) {
    const current = groups[groups.length - 1];
    if (current?.page.id === hit.page.id) current.hits.push(hit);
    else groups.push({ page: hit.page, hits: [hit] });
  }
  return groups;
}

function countLabel(count: number) {
  return count === 1 ? "1 documento" : `${count} documentos`;
}
