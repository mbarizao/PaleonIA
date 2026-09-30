"""Trechos transcritos que entram no índice vetorial."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from paleonia.session.store import annotate_lines


@dataclass(frozen=True)
class Passage:
    part_id: str
    page_id: str
    page_name: str
    line_id: str
    linha_documento: int | None
    linha_transcrita: int | None
    text: str
    confirmed: bool = False

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def passages_from_page(page: dict) -> list[Passage]:
    page_id = str(page.get("id") or "")
    page_name = str(page.get("filename") or page_id)
    found: list[Passage] = []
    for line in annotate_lines(list(page.get("lines") or [])):
        for part in line.get("parts") or []:
            text = str(part.get("text") or "").strip()
            part_id = str(part.get("id") or "")
            if not text or not part_id:
                continue
            found.append(
                Passage(
                    part_id=part_id,
                    page_id=page_id,
                    page_name=page_name,
                    line_id=str(line["id"]),
                    linha_documento=line.get("linha_documento"),
                    linha_transcrita=part.get("linha_transcrita"),
                    text=text,
                    confirmed=bool(part.get("confirmed")),
                )
            )
    return found


def split_passages(
    passages: list[Passage],
    stored: dict[str, str],
) -> tuple[list[Passage], list[Passage], list[str]]:
    """Separa o que precisa de vetor novo, o que só muda de lugar e o que saiu da página.

    `stored` mapeia o id da parte para o hash do texto já gravado.
    """
    current = {passage.part_id for passage in passages}
    to_embed = [passage for passage in passages if stored.get(passage.part_id) != passage.content_hash]
    to_refresh = [passage for passage in passages if stored.get(passage.part_id) == passage.content_hash]
    to_delete = [part_id for part_id in stored if part_id not in current]
    return to_embed, to_refresh, to_delete
