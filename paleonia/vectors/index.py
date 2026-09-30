"""Transcrições gravadas no Postgres, com vetor para a busca."""
from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from paleonia.config import Settings, get_settings
from paleonia.db.connect import connect, safe_message
from paleonia.db.migrate import EMBEDDING_DIMENSIONS
from paleonia.vectors.embed import embed_texts, vector_literal
from paleonia.vectors.passages import passages_from_page, split_passages

Embed = Callable[[list[str], Settings], list[list[float]]]

_safe_message = safe_message


class VectorIndex:
    def __init__(self, settings: Settings | None = None, embed: Embed | None = None):
        self.settings = settings or get_settings()
        self._embed = embed or _embed_with_settings
        self._pages: dict[str, threading.Lock] = {}
        self._pages_guard = threading.Lock()
        self._embed_guard = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.database_url)

    def save_page(self, page: dict, user_id: int | None = None) -> None:
        """Grava o texto da página. O vetor entra em seguida, quando o modelo responde."""
        if not self.enabled:
            return
        page_id = str(page.get("id") or "")
        if not page_id:
            return
        with self._page_lock(page_id):
            self._save_page(page_id, page, user_id)

    def embed_page(self, page_id: str) -> int:
        if not self.enabled or not page_id:
            return 0
        with self._embed_guard:
            with self._page_lock(page_id):
                return self._embed_rows(page_id=page_id)

    def embed_outstanding(self) -> int:
        if not self.enabled:
            return 0
        total = 0
        while True:
            with self._embed_guard:
                count = self._embed_rows(limit=32)
            total += count
            if count < 32:
                return total

    def remove_page(self, page_id: str) -> None:
        if not self.enabled or not page_id:
            return
        with self._page_lock(page_id):
            with connect(self.settings.database_url) as conn:
                conn.execute("DELETE FROM transcriptions WHERE page_id = %s", (page_id,))

    def search(
        self,
        query: str,
        limit: int = 8,
        user_id: int | None = None,
        *,
        confirmed_only: bool = False,
        exclude_part_ids: list[str] | None = None,
    ) -> list[dict]:
        if not self.enabled:
            raise RuntimeError("Defina DATABASE_URL para usar a busca vetorial.")
        text = query.strip()
        if not text:
            raise ValueError("Informe o texto da busca.")
        self._check_dimensions()
        capped = max(1, min(int(limit), 20))
        excluded = [item for item in (exclude_part_ids or []) if item]
        vector = self._embed([text[:2000]], self.settings)[0]
        literal = vector_literal(vector)
        with connect(self.settings.database_url) as conn:
            rows = conn.execute(
                """
                SELECT page_id, page_name, line_id, part_id, linha_documento, linha_transcrita, text,
                       1 - (embedding <=> %s::vector) AS score
                FROM transcriptions
                WHERE embedding IS NOT NULL
                  AND (%s::bigint IS NULL OR user_id = %s OR user_id IS NULL)
                  AND (%s = FALSE OR confirmed)
                  AND NOT (part_id = ANY(%s::text[]))
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (literal, user_id, user_id, bool(confirmed_only), excluded, literal, capped),
            ).fetchall()
        return [_hit(row) for row in rows]

    def confirmed_texts(self, user_id: int | None = None) -> list[str]:
        """Textos conferidos, os mais recentes primeiro. Não exige vetor."""
        if not self.enabled:
            return []
        with connect(self.settings.database_url) as conn:
            rows = conn.execute(
                """
                SELECT text
                FROM transcriptions
                WHERE confirmed
                  AND (%s::bigint IS NULL OR user_id = %s OR user_id IS NULL)
                ORDER BY updated_at DESC
                LIMIT 4000
                """,
                (user_id, user_id),
            ).fetchall()
        return [str(row[0]) for row in rows if str(row[0]).strip()]

    def _save_page(self, page_id: str, page: dict, user_id: int | None) -> None:
        passages = passages_from_page(page)
        with connect(self.settings.database_url) as conn:
            if not passages:
                conn.execute("DELETE FROM transcriptions WHERE page_id = %s", (page_id,))
                return
            stored_rows = conn.execute(
                "SELECT part_id, content_hash FROM transcriptions WHERE page_id = %s",
                (page_id,),
            ).fetchall()
            stored = {row[0]: row[1] for row in stored_rows}
            to_write, to_refresh, to_delete = split_passages(passages, stored)
            if to_delete:
                conn.execute(
                    "DELETE FROM transcriptions WHERE page_id = %s AND part_id = ANY(%s)",
                    (page_id, to_delete),
                )
            with conn.cursor() as cur:
                if to_refresh:
                    cur.executemany(
                        """
                        UPDATE transcriptions
                        SET user_id = %s, page_name = %s, line_id = %s,
                            linha_documento = %s, linha_transcrita = %s,
                            confirmed = %s, updated_at = now()
                        WHERE part_id = %s
                        """,
                        [
                            (
                                user_id,
                                item.page_name,
                                item.line_id,
                                item.linha_documento,
                                item.linha_transcrita,
                                item.confirmed,
                                item.part_id,
                            )
                            for item in to_refresh
                        ],
                    )
                if to_write:
                    cur.executemany(
                        """
                        INSERT INTO transcriptions (
                            user_id, page_id, page_name, line_id, part_id,
                            linha_documento, linha_transcrita, text, content_hash,
                            confirmed, embedding
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                        ON CONFLICT (part_id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            page_id = EXCLUDED.page_id,
                            page_name = EXCLUDED.page_name,
                            line_id = EXCLUDED.line_id,
                            linha_documento = EXCLUDED.linha_documento,
                            linha_transcrita = EXCLUDED.linha_transcrita,
                            text = EXCLUDED.text,
                            content_hash = EXCLUDED.content_hash,
                            confirmed = EXCLUDED.confirmed,
                            embedding = NULL,
                            updated_at = now()
                        """,
                        [
                            (
                                user_id,
                                item.page_id,
                                item.page_name,
                                item.line_id,
                                item.part_id,
                                item.linha_documento,
                                item.linha_transcrita,
                                item.text,
                                item.content_hash,
                                item.confirmed,
                            )
                            for item in to_write
                        ],
                    )

    def _embed_rows(self, page_id: str | None = None, limit: int = 64) -> int:
        self._check_dimensions()
        with connect(self.settings.database_url) as conn:
            if page_id:
                rows = conn.execute(
                    """
                    SELECT part_id, text, content_hash
                    FROM transcriptions
                    WHERE page_id = %s AND embedding IS NULL
                    ORDER BY id
                    """,
                    (page_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT part_id, text, content_hash
                    FROM transcriptions
                    WHERE embedding IS NULL
                    ORDER BY id
                    LIMIT %s
                    """,
                    (limit,),
                ).fetchall()
        if not rows:
            return 0
        vectors = self._embed([row[1] for row in rows], self.settings)
        if len(vectors) != len(rows):
            raise RuntimeError("A geração de vetores devolveu uma quantidade diferente de textos.")
        with connect(self.settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    UPDATE transcriptions
                    SET embedding = %s::vector, updated_at = now()
                    WHERE part_id = %s AND content_hash = %s AND embedding IS NULL
                    """,
                    [(vector_literal(vector), row[0], row[2]) for row, vector in zip(rows, vectors)],
                )
        return len(rows)

    def _check_dimensions(self) -> None:
        configured = int(self.settings.embed_dimensions)
        if configured != EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"EMBED_DIMENSIONS está em {configured}, mas a migration 002_transcriptions "
                f"grava vector({EMBEDDING_DIMENSIONS}). Ajuste o .env para {EMBEDDING_DIMENSIONS} "
                "ou crie outra migration."
            )

    def _page_lock(self, page_id: str) -> threading.Lock:
        with self._pages_guard:
            lock = self._pages.get(page_id)
            if lock is None:
                lock = threading.Lock()
                self._pages[page_id] = lock
            return lock


def persist_page(index: VectorIndex, page: dict, user_id: int | None = None) -> None:
    if not index.enabled:
        return
    index.save_page(page, user_id)
    schedule_embed(index, str(page.get("id") or ""))


def schedule_embed(index: VectorIndex, page_id: str) -> None:
    if not index.enabled or not page_id:
        return

    def run() -> None:
        try:
            index.embed_page(page_id)
        except Exception as exc:
            print(f"Vetor da transcrição: {safe_message(exc)}", file=sys.stderr)

    threading.Thread(target=run, name="paleonia-vector-embed", daemon=True).start()


def schedule_embed_outstanding(index: VectorIndex) -> None:
    if not index.enabled:
        return

    def run() -> None:
        try:
            index.embed_outstanding()
        except Exception as exc:
            print(f"Vetor da transcrição: {safe_message(exc)}", file=sys.stderr)

    threading.Thread(target=run, name="paleonia-vector-backfill", daemon=True).start()


def schedule_remove(index: VectorIndex, page_id: str) -> None:
    if not index.enabled:
        return

    def run() -> None:
        try:
            index.remove_page(page_id)
        except Exception as exc:
            print(f"Transcrição: {safe_message(exc)}", file=sys.stderr)

    threading.Thread(target=run, name="paleonia-vector-index", daemon=True).start()


def _embed_with_settings(texts: list[str], settings: Settings) -> list[list[float]]:
    return embed_texts(texts, settings)


def _hit(row) -> dict:
    score = float(row[7])
    return {
        "page_id": row[0],
        "filename": row[1],
        "line_id": row[2],
        "part_id": row[3],
        "linha_documento": row[4],
        "linha_transcrita": row[5],
        "text": row[6],
        "score": round(max(0.0, min(score, 1.0)), 4),
    }
