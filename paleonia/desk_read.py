"""Lê as faixas da página com o modelo configurado no PaleonIA."""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from paleonia.config import get_settings, load_settings
from paleonia.desk_store import DeskStore, annotate_lines
from paleonia.enhance import crop_dark_border, prepare_for_reading
from paleonia.preprocess import load_image

Progress = Callable[[str, int, int], None]


def read_page_lines(
    store: DeskStore,
    page_id: str,
    *,
    ask: Callable[[str, np.ndarray], dict] | None = None,
    only_empty: bool = True,
    progress: Progress | None = None,
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

    failures: list[str] = []
    for index, group in enumerate(groups, start=1):
        first = group[0]["linha_documento"]
        last = group[-1]["linha_documento"]
        span = f"D-{first:03d}" if first == last else f"D-{first:03d} a D-{last:03d}"
        if progress:
            progress(f"Lendo {span} ({index} de {len(groups)})", index - 1, len(groups))
        before = groups[index - 2][-1] if index > 1 else None
        after = groups[index][0] if index < len(groups) else None
        crop = _crop(image, group, before=before, after=after)
        try:
            payload = reader(_prompt(len(group)), crop)
        except Exception as exc:
            failures.append(f"{span}: {exc}")
            continue
        texts = {
            line["id"]: text
            for line, text in zip(group, _texts_from_payload(payload, len(group)))
        }
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
    from paleonia.ask import ask

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


def _crop(
    image: np.ndarray,
    lines: list[dict],
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> np.ndarray:
    """Empilha cada linha já separada da vizinha, com uma faixa clara entre elas."""
    height, width = image.shape[:2]
    strips: list[np.ndarray] = []
    for index, line in enumerate(lines):
        box = [int(value) for value in line["box"]]
        previous = lines[index - 1]["box"] if index else (before["box"] if before else None)
        following = lines[index + 1]["box"] if index + 1 < len(lines) else (after["box"] if after else None)
        top, bottom = _vertical_band(box, previous, following)
        left = max(0, box[0] - 8)
        right = min(width, box[2] + 8)
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


def _prompt(count: int) -> str:
    slots = ", ".join('"..."' for _ in range(count))
    noun = "linha" if count == 1 else "linhas"
    separated = " Cada linha está isolada, com uma faixa clara entre uma e outra." if count > 1 else ""
    return (
        f"Esta imagem é um recorte de manuscrito com {count} {noun} de escrita, de cima para baixo.{separated}\n"
        "Transcreva cada linha na mesma ordem.\n"
        "Preserve a grafia original, abreviações, acentos, números e traços.\n"
        "Não modernize, não explique, não traduza e não invente.\n"
        "Se um trecho não puder ser lido, use [ilegível].\n"
        "Se a linha não tiver escrita, use [sem texto].\n"
        "Responda somente JSON:\n"
        f'{{"linhas":[{slots}]}}'
    )


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
