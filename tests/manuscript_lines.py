from __future__ import annotations

import cv2
import numpy as np


def detect_manuscript_lines(image: np.ndarray, sensitivity: float = 0.55) -> list[list[int]]:
    """Caixas [x0, y0, x1, y1] de cada linha escrita, na ordem de leitura.

    Num livro aberto, as linhas da página esquerda vêm antes das da direita.
    `sensitivity` entre 0,15 e 0,90: mais alto conserva linhas mais fracas.
    """
    gray = _gray(image)
    height, width = gray.shape
    if height < 16 or width < 16:
        return []

    sensitivity = float(np.clip(sensitivity, 0.15, 0.9))
    boxes: list[list[int]] = []
    for x_offset, page in _page_slices(gray):
        ink = _ink_mask(page)
        found = _lines_on_page(ink, sensitivity)
        page_h = page.shape[0]
        for box in _separate(found):
            box[0] += x_offset
            box[2] += x_offset
            box[1] = max(0, box[1])
            box[3] = min(page_h, box[3])
            if box[3] - box[1] > page_h * 0.25:
                continue
            boxes.append(box)
    return boxes[:300]


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if gray.dtype != np.uint8:
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return gray


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    """Tinta escura, com o fundo estimado numa imagem reduzida para ir mais rápido."""
    height, width = gray.shape
    sample_w = min(width, 640)
    sample_h = max(1, int(round(height * (sample_w / width))))
    small = cv2.resize(gray, (sample_w, sample_h), interpolation=cv2.INTER_AREA)
    background = cv2.GaussianBlur(small, (0, 0), sigmaX=18)
    background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    flat = cv2.divide(gray, np.maximum(background, 1), scale=255)
    flat = cv2.normalize(flat, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    block = 31 if min(height, width) >= 48 else 15
    return cv2.adaptiveThreshold(
        flat,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block,
        11,
    )


def _page_slices(gray: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """Divide um livro aberto na lombada. Uma página só volta inteira."""
    height, width = gray.shape
    gutter = _gutter_x(gray) if width > height * 1.2 else None
    if gutter is None:
        return [(0, gray)]
    return [(0, gray[:, :gutter]), (gutter, gray[:, gutter:])]


def _gutter_x(gray: np.ndarray) -> int | None:
    columns = gray.mean(axis=0).astype(np.float32)
    smooth = cv2.GaussianBlur(columns.reshape(1, -1), (1, 31), 0).ravel()
    width = int(smooth.size)
    left = int(width * 0.4)
    right = int(width * 0.6)
    center = smooth[left:right]
    if center.size < 10:
        return None
    gutter = left + int(np.argmin(center))
    before = smooth[max(0, gutter - 90) : max(0, gutter - 20)]
    after = smooth[min(width, gutter + 20) : min(width, gutter + 90)]
    if before.size == 0 or after.size == 0:
        return None
    dip = float(min(before.mean(), after.mean()) - smooth[gutter])
    if dip < 18:
        return None
    return gutter


def _lines_on_page(ink: np.ndarray, sensitivity: float) -> list[list[int]]:
    grid = _rule_grid(ink)
    if grid:
        return _bands_between_rules(ink, grid, sensitivity)
    return _lines_from_projection(ink, sensitivity)


def _rule_grid(ink: np.ndarray) -> list[int]:
    """Centros Y de uma pauta impressa regular. Lista vazia se não houver pauta."""
    height, width = ink.shape
    length = max(50, int(width * 0.45))
    if length >= width:
        length = max(3, width - 1)
    rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    active = (rules > 0).sum(axis=1) > width * 0.35
    runs = [run for run in _runs(active) if 1 <= run[1] - run[0] <= 5]
    centers = [(start + end) // 2 for start, end in runs]
    if len(centers) < 8:
        return []
    gaps = np.diff(centers)
    median = float(np.median(gaps))
    if median < 8:
        return []
    grouped: list[list[int]] = [[centers[0]]]
    for previous, nxt, gap in zip(centers, centers[1:], gaps):
        if median * 0.7 <= float(gap) <= median * 1.45:
            grouped[-1].append(int(nxt))
        else:
            grouped.append([int(nxt)])
    grid = max(grouped, key=len)
    return grid if len(grid) >= 8 else []


def _bands_between_rules(ink: np.ndarray, grid: list[int], sensitivity: float) -> list[list[int]]:
    text = _without_thin_rules(ink)
    spacing = float(np.median(np.diff(grid)))
    edges = [max(0, int(grid[0] - spacing))] + grid + [min(ink.shape[0], int(grid[-1] + spacing))]
    density_limit = 0.006 + (1.0 - sensitivity) * 0.02
    boxes: list[list[int]] = []
    for top, bottom in zip(edges, edges[1:]):
        if bottom - top < 8 or bottom - top > spacing * 1.8:
            continue
        band = text[top:bottom]
        if band.size == 0 or float((band > 0).mean()) < density_limit:
            continue
        box = _box_from_ink(band, top, ink.shape[1])
        if box is not None:
            boxes.append(box)
    return boxes


def _lines_from_projection(ink: np.ndarray, sensitivity: float) -> list[list[int]]:
    height, width = ink.shape
    source = _without_thin_rules(ink)
    if float((source > 0).mean()) < 0.001:
        source = ink
    gap = max(9, width // 70)
    linked = cv2.dilate(source, cv2.getStructuringElement(cv2.MORPH_RECT, (gap, 1)))
    projection = (linked > 0).sum(axis=1).astype(np.float32)
    if float(projection.max()) <= 0:
        return []
    smooth = cv2.GaussianBlur(projection.reshape(-1, 1), (1, 5), 0).ravel()
    fraction = float(np.clip(0.175 - sensitivity * 0.17, 0.02, 0.2))
    runs = _runs(smooth >= max(8.0, fraction * width))
    heights = [end - start for start, end in runs if end - start >= 3]
    if not heights:
        return []
    median_h = float(np.median(heights))
    merged = _merge(runs, max(3, int(round(median_h * 0.55))))
    min_h = max(6, int(round(median_h * 0.45)))
    max_h = max(int(round(median_h * 5)), int(height * 0.1))
    boxes: list[list[int]] = []
    for start, end in merged:
        if end - start < min_h or end - start > max_h or end - start > height * 0.25:
            continue
        box = _box_from_ink(source[start:end], start, width, pad_y=max(2, int(round((end - start) * 0.12))))
        if box is not None:
            boxes.append(box)
    return boxes


def _without_thin_rules(ink: np.ndarray) -> np.ndarray:
    height, width = ink.shape
    length = max(50, int(width * 0.45))
    if length >= width:
        return ink
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    active = (lines > 0).sum(axis=1) > width * 0.35
    thin = np.zeros(height, dtype=bool)
    for start, end in _runs(active):
        if end - start <= 5:
            thin[start:end] = True
    if not thin.any():
        return ink
    mask = np.repeat(thin[:, None], width, axis=1)
    mask = cv2.dilate(mask.astype(np.uint8) * 255, np.ones((3, 1), np.uint8))
    return cv2.subtract(ink, mask)


def _box_from_ink(band: np.ndarray, y_offset: int, width: int, pad_y: int = 1) -> list[int] | None:
    if band.size == 0 or float((band > 0).mean()) < 0.004:
        return None
    columns = np.flatnonzero((band > 0).any(axis=0))
    if columns.size < 12:
        return None
    pad_x = max(8, width // 100)
    x0 = max(0, int(columns[0]) - pad_x)
    x1 = min(width, int(columns[-1]) + pad_x + 1)
    y0 = max(0, y_offset - pad_y)
    y1 = y_offset + band.shape[0] + pad_y
    if x1 - x0 < 16 or y1 - y0 < 6:
        return None
    return [x0, y0, x1, y1]


def _runs(active: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    flags = active.tolist() if not isinstance(active, list) else active
    for index, on in enumerate(flags):
        if on and start is None:
            start = index
        elif not on and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _merge(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged: list[list[int]] = [list(runs[0])]
    for start, end in runs[1:]:
        if start - merged[-1][1] <= max_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _separate(boxes: list[list[int]]) -> list[list[int]]:
    boxes.sort(key=lambda box: (box[1], box[0]))
    for index in range(len(boxes) - 1):
        current = boxes[index]
        nxt = boxes[index + 1]
        if current[3] <= nxt[1]:
            continue
        mid = (current[3] + nxt[1]) // 2
        if mid - current[1] >= 4 and nxt[3] - mid >= 4:
            current[3] = mid
            nxt[1] = mid
    return boxes
