"use client";

import { SearchOutlined } from "@ant-design/icons";
import { Input } from "antd";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { SearchHit, SearchResponse } from "@/lib/types";
import { pad } from "@/lib/lines";

type Props = {
  onOpen: (hit: SearchHit) => void;
};

export function CorpusSearch({ onOpen }: Props) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [detail, setDetail] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) {
      setHits([]);
      setDetail("");
      setOpen(false);
      return;
    }
    const timer = window.setTimeout(() => {
      void api<SearchResponse>(`/api/search?q=${encodeURIComponent(text)}&limit=8`)
        .then((data) => {
          setHits(data.results);
          setDetail(data.enabled ? (data.results.length ? "" : "Nenhuma passagem parecida.") : data.detail || "Busca vetorial desligada.");
          setOpen(true);
        })
        .catch((error: Error) => {
          setHits([]);
          setDetail(error.message);
          setOpen(true);
        });
    }, 320);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="corpus-search" ref={box}>
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder="Buscar no acervo"
        value={query}
        aria-label="Buscar no acervo"
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => {
          if (query.trim().length >= 2) setOpen(true);
        }}
      />
      {open ? (
        <div className="search-results" role="listbox">
          {detail ? <p className="search-detail">{detail}</p> : null}
          {hits.map((hit) => (
            <button
              key={`${hit.page_id}-${hit.part_id}`}
              type="button"
              className="search-hit"
              onClick={() => {
                setOpen(false);
                onOpen(hit);
              }}
            >
              <span className="search-hit-meta">
                {hit.filename}
                {hit.linha_documento ? ` · D-${pad(hit.linha_documento)}` : ""}
                {hit.linha_transcrita ? ` · T-${pad(hit.linha_transcrita)}` : ""}
                <span>{Math.round(hit.score * 100)}%</span>
              </span>
              <span className="search-hit-text">{hit.text}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
