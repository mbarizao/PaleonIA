"""Lê as faixas da página com o modelo configurado no PaleonIA."""
from __future__ import annotations

import sys
from collections.abc import Callable

import cv2
import numpy as np

from paleonia.config import get_settings, load_settings
from paleonia.db.connect import safe_message
from paleonia.image_enhance.enhance import crop_dark_border, prepare_for_reading
from paleonia.image_enhance.preprocess import load_image
from paleonia.reading.precedent import (
    MAX_NEIGHBORS,
    forms_from_texts,
    has_gap,
    neighbor_texts,
    revise_gap_texts,
)
from paleonia.session.store import DeskStore, annotate_lines

Progress = Callable[[str, int, int], None]


def read_page_lines(
    store: DeskStore,
    page_id: str,
    *,
    ask: Callable[[str, np.ndarray], dict] | None = None,
    only_empty: bool = True,
    progress: Progress | None = None,
    precedents=None,
    user_id: int | None = None,
) -> dict:
    path = store.require_image(page_id)
    image = load_image(path, invalid="Não foi possível ler a imagem da página.")

    if ask is None:
        load_settings()
        reader = default_ask
    else:
        reader = ask
    targets = _pending_lines(store, page_id, only_empty=only_empty)
    groups = _groups(targets)
    if not groups:
        if progress:
            progress("Nenhuma linha vazia para ler.", 0, 0)
        return store.public_page(store._require(page_id))
    if not store._require(page_id).get("prepared"):
        image = prepare_for_reading(image)

    forms, lookup = _precedent_tools(precedents, user_id)
    page_boxes = [line["box"] for line in store._require(page_id).get("lines") or []]
    gutter = column_gutter(image, page_boxes)
    failures: list[str] = []
    for index, group in enumerate(groups, start=1):
        first = group[0]["linha_documento"]
        last = group[-1]["linha_documento"]
        span = f"D-{first:03d}" if first == last else f"D-{first:03d} a D-{last:03d}"
        if progress:
            progress(f"Lendo {span} ({index} de {len(groups)})", index - 1, len(groups))
        before = groups[index - 2][-1] if index > 1 else None
        after = groups[index][0] if index < len(groups) else None
        crop = _crop(image, group, before=before, after=after, gutter=gutter)
        try:
            payload = reader(_prompt(len(group), forms, two_columns=gutter is not None), crop)
        except Exception as exc:
            failures.append(f"{span}: {exc}")
            continue
        written = _texts_from_payload(payload, len(group))
        if lookup is not None and any(has_gap(text) for text in written):
            if progress:
                progress(f"Consultando precedentes de {span}", index - 1, len(groups))
            part_ids = [part_id for line in group for part_id in line.get("part_ids") or []]
            written = revise_gap_texts(
                written,
                lookup=lambda query, ids=part_ids: lookup(query, ids),
                reread=lambda neighbors, span_crop=crop, count=len(group): _texts_from_payload(
                    reader(_prompt(count, forms, neighbors, two_columns=gutter is not None), span_crop),
                    count,
                ),
            )
        texts = {line["id"]: text for line, text in zip(group, written)}
        store.set_line_texts(page_id, texts, only_empty=only_empty)
        if progress:
            progress(f"Lendo {span} ({index} de {len(groups)})", index, len(groups))

    page = store.public_page(store._require(page_id))
    if failures and len(failures) == len(groups):
        raise RuntimeError(failures[0])
    if failures and progress:
        progress("Leitura parcial. " + failures[0], len(groups), len(groups))
    elif progress:
        progress("Transcrição pronta.", len(groups), len(groups))
    return page


def default_ask(prompt: str, image: np.ndarray) -> dict:
    from paleonia.reading.ask import ask

    return ask(load_settings(), prompt, image)


def _pending_lines(store: DeskStore, page_id: str, *, only_empty: bool) -> list[dict]:
    page = store._require(page_id)
    raw = {line["id"]: line for line in page["lines"]}
    pending = []
    for line in annotate_lines(page["lines"]):
        source = raw[line["id"]]
        if not source.get("include", True):
            continue
        if only_empty and any((part.get("text") or "").strip() for part in source.get("parts") or []):
            continue
        pending.append(
            {
                "id": source["id"],
                "box": list(source["box"]),
                "linha_documento": line["linha_documento"],
                "part_ids": [str(part["id"]) for part in source.get("parts") or [] if part.get("id")],
            }
        )
    return pending


def _groups(lines: list[dict], *, max_height: int | None = None, max_count: int | None = None) -> list[list[dict]]:
    settings = get_settings()
    if max_height is None:
        max_height = settings.read_group_max_height
    if max_count is None:
        max_count = settings.read_group_max_count
    groups: list[list[dict]] = []
    current: list[dict] = []
    top = 0
    for line in lines:
        y0 = int(line["box"][1])
        y1 = int(line["box"][3])
        jumped = bool(current) and y0 < int(current[-1]["box"][1])
        too_tall = bool(current) and y1 - top > max_height
        too_many = len(current) >= max_count
        if current and (jumped or too_tall or too_many):
            groups.append(current)
            current = []
        if not current:
            top = y0
        current.append(line)
    if current:
        groups.append(current)
    return groups


def _x_overlap(a: list[int], b: list[int]) -> int:
    return min(int(a[2]), int(b[2])) - max(int(a[0]), int(b[0]))


def _vertical_band(box: list[int], previous: list[int] | None, following: list[int] | None) -> tuple[int, int]:
    """Recorta a faixa no meio do vão até a linha vizinha, para não levar o texto dela."""
    y0, y1 = int(box[1]), int(box[3])
    center = (y0 + y1) / 2
    if previous is not None and _x_overlap(box, previous) >= 24:
        previous_center = (int(previous[1]) + int(previous[3])) / 2
        y0 = max(y0, int(round((previous_center + center) / 2)))
    if following is not None and _x_overlap(box, following) >= 24:
        following_center = (int(following[1]) + int(following[3])) / 2
        y1 = min(y1, int(round((center + following_center) / 2)))
    if y1 - y0 < 14:
        return int(box[1]), int(box[3])
    return y0, y1


def column_gutter(image: np.ndarray, boxes: list[list[int]]) -> tuple[int, int] | None:
    """Vão vertical entre dois textos lado a lado. (fim da coluna esquerda, início da direita)."""
    found = _ink_gutter(image)
    if found is None:
        found = _box_gutter(boxes, int(image.shape[1]))
    if found is None or not _gutter_matches(found, boxes):
        return None
    return found


def _ink_gutter(image: np.ndarray) -> tuple[int, int] | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    if width < 240 or height < 80:
        return None
    top = int(height * 0.08)
    bottom = int(height * 0.92)
    ink = (gray[top:bottom] < 185).astype(np.float32)
    if ink.size == 0:
        return None
    density = ink.mean(axis=0)
    kernel = max(9, width // 80)
    if kernel % 2 == 0:
        kernel += 1
    smooth = cv2.GaussianBlur(density.reshape(1, -1), (kernel, 1), 0).ravel()
    left = int(width * 0.18)
    right = int(width * 0.82)
    if right - left < 40:
        return None
    valley = left + int(np.argmin(smooth[left:right]))
    if valley < 12 or valley > width - 12:
        return None
    left_peak = float(smooth[:valley].max())
    right_peak = float(smooth[valley + 1 :].max()) if valley + 1 < width else 0.0
    if left_peak < 0.015 or right_peak < 0.015:
        return None
    limit = min(left_peak, right_peak) * 0.45
    if float(smooth[valley]) > limit:
        return None
    x0 = valley
    while x0 > 0 and float(smooth[x0]) <= limit:
        x0 -= 1
    x1 = valley
    while x1 < width - 1 and float(smooth[x1]) <= limit:
        x1 += 1
    if x1 - x0 < max(12, width // 80):
        return None
    if x0 < width * 0.12 or x1 > width * 0.88:
        return None
    return int(x0), int(x1)


def _box_gutter(boxes: list[list[int]], width: int) -> tuple[int, int] | None:
    if width < 240 or len(boxes) < 4:
        return None
    coverage = np.zeros(width, dtype=np.float32)
    for box in boxes:
        x0 = max(0, min(width, int(box[0])))
        x1 = max(0, min(width, int(box[2])))
        if x1 > x0:
            coverage[x0:x1] += 1
    if float(coverage.max()) < 2:
        return None
    kernel = max(9, width // 80)
    if kernel % 2 == 0:
        kernel += 1
    smooth = cv2.GaussianBlur(coverage.reshape(1, -1), (kernel, 1), 0).ravel()
    left = int(width * 0.18)
    right = int(width * 0.82)
    valley = left + int(np.argmin(smooth[left:right]))
    left_peak = float(smooth[:valley].max()) if valley else 0.0
    right_peak = float(smooth[valley + 1 :].max()) if valley + 1 < width else 0.0
    if left_peak < 2 or right_peak < 2:
        return None
    limit = min(left_peak, right_peak) * 0.45
    if float(smooth[valley]) > limit:
        return None
    x0 = valley
    while x0 > 0 and float(smooth[x0]) <= limit:
        x0 -= 1
    x1 = valley
    while x1 < width - 1 and float(smooth[x1]) <= limit:
        x1 += 1
    if x1 - x0 < max(12, width // 80) or x0 < width * 0.12 or x1 > width * 0.88:
        return None
    return int(x0), int(x1)


def _gutter_matches(gutter: tuple[int, int], boxes: list[list[int]]) -> bool:
    left_end, right_start = gutter
    left = right = crossing = 0
    for box in boxes:
        x0, x1 = int(box[0]), int(box[2])
        center = (x0 + x1) / 2
        if center < left_end:
            left += 1
        elif center > right_start:
            right += 1
        if x0 < left_end - 8 and x1 > right_start + 8:
            crossing += 1
    if left >= 2 and right >= 2:
        return True
    return crossing >= 2 and left + right + crossing >= 4


def _limit_box(box: list[int], gutter: tuple[int, int] | None) -> list[int]:
    """Corta a faixa no vão, para a leitura não levar o texto da outra coluna."""
    x0, y0, x1, y1 = [int(value) for value in box[:4]]
    if gutter is None or x1 <= gutter[0] or x0 >= gutter[1]:
        return [x0, y0, x1, y1]
    left_end, right_start = gutter
    on_left = max(0, min(x1, left_end) - x0)
    on_right = max(0, x1 - max(x0, right_start))
    if on_left >= on_right:
        x1 = min(x1, left_end)
    else:
        x0 = max(x0, right_start)
    if x1 - x0 < 24:
        return [int(value) for value in box[:4]]
    return [x0, y0, x1, y1]


def _crop(
    image: np.ndarray,
    lines: list[dict],
    *,
    before: dict | None = None,
    after: dict | None = None,
    gutter: tuple[int, int] | None = None,
) -> np.ndarray:
    """Empilha cada linha já separada da vizinha, com uma faixa clara entre elas."""
    height, width = image.shape[:2]
    strips: list[np.ndarray] = []
    for index, line in enumerate(lines):
        raw = [int(value) for value in line["box"]]
        box = _limit_box(raw, gutter)
        previous = lines[index - 1]["box"] if index else (before["box"] if before else None)
        following = lines[index + 1]["box"] if index + 1 < len(lines) else (after["box"] if after else None)
        top, bottom = _vertical_band(raw, previous, following)
        left = max(0, box[0] - 8)
        right = min(width, box[2] + 8)
        if gutter is not None:
            if box[2] <= gutter[0]:
                right = min(right, gutter[0])
            elif box[0] >= gutter[1]:
                left = max(left, gutter[1])
        top = max(0, top)
        bottom = min(height, bottom)
        if bottom <= top or right <= left:
            continue
        strips.append(crop_dark_border(image[top:bottom, left:right]))
    if not strips:
        return image
    gap = 18
    out_width = max(strip.shape[1] for strip in strips)
    out_height = sum(strip.shape[0] for strip in strips) + gap * (len(strips) - 1)
    canvas = np.full((out_height, out_width, 3), 245, np.uint8)
    y = 0
    for strip in strips:
        strip_height, strip_width = strip.shape[:2]
        canvas[y : y + strip_height, 0:strip_width] = strip
        y += strip_height + gap
    return canvas


def _prompt(
    count: int,
    forms: list[str] | None = None,
    precedents: list[str] | None = None,
    *,
    two_columns: bool = False,
) -> str:
    slots = ", ".join('"..."' for _ in range(count))
    noun = "linha" if count == 1 else "linhas"
    separated = " Cada linha está isolada, com uma faixa clara entre uma e outra." if count > 1 else ""
    text = (
        f"Esta imagem é um recorte de manuscrito com {count} {noun} de escrita, de cima para baixo.{separated}\n"
        "Transcreva cada linha na mesma ordem.\n"
        "Preserve a grafia original, abreviações, acentos, números e traços.\n"
        "Não modernize, não explique, não traduza e não invente.\n"
        "Se um trecho não puder ser lido, use [ilegível].\n"
        "Se a linha não tiver escrita, use [sem texto].\n"
        "Responda somente JSON:\n"
        f'{{"linhas":[{slots}]}}'
    )
    if two_columns:
        text += "\nA página tem dois textos lado a lado. Transcreva só o texto desta faixa, sem a coluna vizinha."
    if forms:
        text += "\nFormas já conferidas neste acervo, que podem reaparecer: " + ", ".join(forms) + "."
    if precedents:
        quoted = "\n".join(f"- {item}" for item in precedents)
        text += (
            "\nNesta leitura há trechos [ilegível]. Linhas já conferidas com fraseado parecido:\n"
            f"{quoted}\n"
            "Use essas linhas só como precedente de grafia e fórmula. "
            "Se a imagem não sustentar a palavra, mantenha [ilegível]."
        )
    return text


def _precedent_tools(precedents, user_id: int | None):
    """Devolve as formas repetidas e a consulta aos vizinhos, ou nada se o acervo falhar."""
    if precedents is None:
        return [], None
    try:
        raw = precedents.confirmed_texts(user_id)
        forms = forms_from_texts([str(item) for item in raw])
    except Exception as exc:
        print(f"Precedentes: {safe_message(exc)}", file=sys.stderr)
        return [], None

    def lookup(query: str, part_ids: list[str]) -> list[str]:
        hits = precedents.search(
            query,
            limit=MAX_NEIGHBORS,
            user_id=user_id,
            confirmed_only=True,
            exclude_part_ids=part_ids,
        )
        return neighbor_texts(hits)

    return forms, lookup


def _texts_from_payload(payload: dict, count: int) -> list[str]:
    raw = payload.get("linhas") if isinstance(payload, dict) else None
    if isinstance(raw, str):
        raw = raw.splitlines()
    if not isinstance(raw, list):
        raw = []
    texts: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("texto") or item.get("text") or ""
        texts.append(_clean_reading(str(item)))
    if len(texts) == 1 and count > 1 and "\n" in texts[0]:
        texts = [_clean_reading(line) for line in texts[0].splitlines()]
    if len(texts) < count:
        texts.extend([""] * (count - len(texts)))
    return texts[:count]


def _clean_reading(text: str) -> str:
    cleaned = text.strip()
    if cleaned.lower() in {"[sem texto]", "sem texto"}:
        return ""
    return cleaned
