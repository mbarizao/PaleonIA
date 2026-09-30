from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from paleonia.image_enhance.preprocess import ImageInput, _clahe, load_image


@dataclass
class EnhanceParams:
    clahe_clip: float = 1.8
    gamma: float = 0.88
    denoise: float = 5.0
    background_sigma: float = 40.0
    unsharp: float = 0.2
    brightness: int = 6
    contrast: float = 1.12
    bleed: float = 0.45

    def clamp(self) -> EnhanceParams:
        return EnhanceParams(
            clahe_clip=float(np.clip(self.clahe_clip, 0.0, 6.0)),
            gamma=float(np.clip(self.gamma, 0.45, 1.8)),
            denoise=float(np.clip(self.denoise, 0.0, 12.0)),
            background_sigma=float(np.clip(self.background_sigma, 0.0, 80.0)),
            unsharp=float(np.clip(self.unsharp, 0.0, 1.2)),
            brightness=int(np.clip(self.brightness, -30, 40)),
            contrast=float(np.clip(self.contrast, 0.7, 1.8)),
            bleed=float(np.clip(self.bleed, 0.0, 1.0)),
        )

    @classmethod
    def from_dict(cls, data: dict) -> EnhanceParams:
        known = {field: data[field] for field in cls.__dataclass_fields__ if field in data}
        return cls(**known).clamp()

    def as_dict(self) -> dict:
        return asdict(self)


def reduce_bleed_through(gray: np.ndarray, strength: float = 0.45) -> np.ndarray:
    """Clareia tinta fraca do verso sem apagar o traço principal."""
    if strength <= 0.02:
        return gray
    paper = float(np.percentile(gray, 90))
    ink = float(np.percentile(gray, 10))
    span = max(paper - ink, 1.0)
    lo = ink + 0.22 * span
    hi = paper - 0.12 * span
    strong = (gray < lo).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 11))
    near_ink = cv2.dilate(strong, kernel, iterations=1)
    bleed = (gray > lo) & (gray < hi) & (near_ink == 0)
    lifted = gray.astype(np.float32)
    lift = 18.0 + 50.0 * strength
    lifted[bleed] = np.minimum(255.0, lifted[bleed] + lift)
    return np.clip(lifted, 0, 255).astype(np.uint8)


def deskew(gray: np.ndarray) -> np.ndarray:
    """Corrige inclinação leve de uma página já recortada."""
    inverted = cv2.bitwise_not(gray)
    _, binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))
    if coords.shape[0] < 400:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.25 or abs(angle) > 7:
        return gray
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def dark_border_window(image: np.ndarray, *, threshold: int = 28, pad: int = 4) -> tuple[int, int, int, int]:
    """Devolve x0, y0, x1, y1 da página sem a moldura escura."""
    if image.size == 0:
        return 0, 0, 0, 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    lit = gray > threshold
    rows = np.where(lit.mean(axis=1) > 0.12)[0]
    cols = np.where(lit.mean(axis=0) > 0.12)[0]
    if rows.size == 0 or cols.size == 0:
        return 0, 0, width, height
    y0 = max(0, int(rows[0]) - pad)
    y1 = min(height, int(rows[-1]) + 1 + pad)
    x0 = max(0, int(cols[0]) - pad)
    x1 = min(width, int(cols[-1]) + 1 + pad)
    if y1 - y0 < height * 0.6 or x1 - x0 < width * 0.6:
        return 0, 0, width, height
    return x0, y0, x1, y1


def crop_dark_border(image: np.ndarray, *, threshold: int = 28, pad: int = 4) -> np.ndarray:
    """Remove a moldura escura do scanner, sem cortar o papel."""
    x0, y0, x1, y1 = dark_border_window(image, threshold=threshold, pad=pad)
    if x0 == 0 and y0 == 0 and x1 == image.shape[1] and y1 == image.shape[0]:
        return image
    return image[y0:y1, x0:x1]


def _neutralize_paper(bgr: np.ndarray) -> np.ndarray:
    """Tira o amarelado: o papel claro vira branco e a tinta permanece escura."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bright = (gray >= np.percentile(gray, 72)) & (gray > 40)
    if float(bright.mean()) < 0.04:
        return bgr
    paper = np.median(bgr[bright], axis=0).astype(np.float32)
    paper = np.maximum(paper, 1.0)
    scale = 242.0 / paper
    balanced = np.clip(bgr.astype(np.float32) * scale, 0, 255)
    return balanced.astype(np.uint8)


_TILE = 512
_TILE_OVERLAP = 96
_TILE_SCALE = 2


def _tile_spans(length: int, tile: int, overlap: int) -> list[tuple[int, int]]:
    if length <= tile:
        return [(0, length)]
    step = max(1, tile - overlap)
    starts = list(range(0, length - tile + 1, step))
    last = length - tile
    if starts[-1] != last:
        starts.append(last)
    return [(start, start + tile) for start in starts]


def _blend_axis(length: int, overlap: int, *, at_start: bool, at_end: bool) -> np.ndarray:
    """Peso 1 no miolo e rampa suave na borda que encontra outro bloco."""
    window = np.ones(length, np.float32)
    fade = min(overlap, length // 2)
    if fade <= 0:
        return window
    ramp = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)
    ramp = ramp * ramp * (3.0 - 2.0 * ramp)
    if not at_start:
        window[:fade] = ramp
    if not at_end:
        window[-fade:] = ramp[::-1]
    return window


_VIEW_LONG_SIDE = 12000


def reading_scale(height: int, width: int) -> int:
    """Escolhe 3×, 2× ou 1× sem passar do lado longo da mesa."""
    longest = max(int(height), int(width), 1)
    for scale in (3, 2, 1):
        if longest * scale <= _VIEW_LONG_SIDE:
            return scale
    return 1


def _zoom_block(gray: np.ndarray, scale: int) -> np.ndarray:
    """Amplia o bloco e reforça o traço nesse tamanho."""
    height, width = gray.shape[:2]
    if scale <= 1 or min(height, width) < 8:
        return gray
    zoomed = cv2.resize(
        gray,
        (width * scale, height * scale),
        interpolation=cv2.INTER_LANCZOS4,
    )
    short = min(zoomed.shape[:2])
    grid = int(np.clip(short // 40, 2, 8))
    zoomed = _clahe(zoomed, clip_limit=1.6, tile=grid)
    sigma = float(np.clip(0.45 * scale, 0.8, 2.2))
    blur = cv2.GaussianBlur(zoomed, (0, 0), sigma)
    sharp = cv2.addWeighted(zoomed, 1.36, blur, -0.36, 0)
    return cv2.bilateralFilter(sharp, d=5, sigmaColor=14, sigmaSpace=3)


def _blend_tiles(
    gray: np.ndarray,
    *,
    tile: int,
    overlap: int,
    scale: int,
    keep_size: bool,
    progress=None,
) -> np.ndarray:
    height, width = gray.shape[:2]
    out_scale = 1 if keep_size else scale
    dest_h = height * out_scale
    dest_w = width * out_scale
    acc = np.zeros((dest_h, dest_w), np.float32)
    weight = np.zeros((dest_h, dest_w), np.float32)
    fade = overlap if keep_size else overlap * scale
    done = 0
    total = len(_tile_spans(height, tile, overlap)) * len(_tile_spans(width, tile, overlap))
    for y0, y1 in _tile_spans(height, tile, overlap):
        for x0, x1 in _tile_spans(width, tile, overlap):
            zoomed = _zoom_block(gray[y0:y1, x0:x1], scale)
            if keep_size:
                refined = zoomed
                if zoomed.shape[0] != y1 - y0 or zoomed.shape[1] != x1 - x0:
                    refined = cv2.resize(zoomed, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
                top, bottom, left, right = y0, y1, x0, x1
                at_top, at_bottom = y0 == 0, y1 == height
                at_left, at_right = x0 == 0, x1 == width
            else:
                refined = zoomed
                top, bottom = y0 * scale, y1 * scale
                left, right = x0 * scale, x1 * scale
                at_top, at_bottom = y0 == 0, y1 == height
                at_left, at_right = x0 == 0, x1 == width
            mask = np.outer(
                _blend_axis(bottom - top, fade, at_start=at_top, at_end=at_bottom),
                _blend_axis(right - left, fade, at_start=at_left, at_end=at_right),
            )
            acc[top:bottom, left:right] += refined.astype(np.float32) * mask
            weight[top:bottom, left:right] += mask
            done += 1
            if progress:
                region = acc[top:bottom, left:right] / np.maximum(weight[top:bottom, left:right], 1e-6)
                # Zero-weight edges belong to tiles that have not arrived yet.
                region = np.where(weight[top:bottom, left:right] > 0, region, refined)
                progress("tile", _lift_paper(np.clip(region, 0, 255).astype(np.uint8)),
                         left, top, out_scale, done, total)
    merged = acc / np.maximum(weight, 1e-6)
    return np.clip(merged, 0, 255).astype(np.uint8)


def refine_tiles(
    gray: np.ndarray,
    *,
    tile: int = _TILE,
    overlap: int = _TILE_OVERLAP,
    scale: int = _TILE_SCALE,
    keep_size: bool = True,
    crop_border: bool = True,
) -> np.ndarray:
    """Trata a página em blocos ampliados e remonta, sem emenda.

    Com `keep_size`, cada bloco volta ao lugar original. Sem isso, a página
    fica no tamanho ampliado, que é o que o zoom da mesa mostra.
    """
    if gray.ndim != 2 or gray.size == 0:
        return gray
    tile = max(32, int(tile))
    overlap = int(np.clip(overlap, 0, tile // 2))
    scale = max(1, int(scale))
    if not keep_size and scale <= 1:
        keep_size = True
        scale = _TILE_SCALE
    height, width = gray.shape[:2]
    if crop_border and keep_size:
        x0, y0, x1, y1 = dark_border_window(gray)
        interior = gray[y0:y1, x0:x1]
        if interior.size == 0:
            return gray
        refined = _blend_tiles(interior, tile=tile, overlap=overlap, scale=scale, keep_size=True)
        if x0 == 0 and y0 == 0 and x1 == width and y1 == height:
            return refined
        merged = gray.copy()
        merged[y0:y1, x0:x1] = refined
        return merged
    return _blend_tiles(gray, tile=tile, overlap=overlap, scale=scale, keep_size=keep_size)


def _frame_depth(dark_lines: np.ndarray) -> int:
    """Profundidade da moldura escura que encosta na borda, sem seguir uma mancha isolada."""
    depths: list[int] = []
    for line in dark_lines:
        if float(line.mean()) > 0.9:
            continue
        if not bool(line[0]):
            depths.append(0)
            continue
        paper = np.flatnonzero(~line)
        depths.append(int(paper[0]) if paper.size else 0)
    if not depths:
        return 0
    return int(np.percentile(depths, 80))


def _shadow_depth(lines: np.ndarray, limit: float, cap: int) -> int:
    """Quanto a sombra da lombada ainda escurece a borda, coluna a coluna."""
    eaten = 0
    for index in range(min(int(lines.shape[1]), cap)):
        if float(np.median(lines[:, index])) >= limit:
            break
        eaten += 1
    return eaten


def refile_window(image: np.ndarray) -> tuple[int, int, int, int]:
    """Corta a moldura escura e a sombra da lombada, inclusive se a borda entra curva."""
    if image.size == 0:
        return 0, 0, 0, 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]
    if height < 16 or width < 16:
        return 0, 0, width, height
    dark = gray < 42
    left = _frame_depth(dark)
    right = _frame_depth(dark[:, ::-1])
    top = _frame_depth(dark.T)
    bottom = _frame_depth(dark.T[:, ::-1])
    halo = int(np.clip(round(min(height, width) * 0.004), 4, 14))
    if left:
        left += halo
    if right:
        right += halo
    if top:
        top += halo
    if bottom:
        bottom += halo
    x0, y0 = left, top
    x1, y1 = width - right, height - bottom
    if y1 - y0 < height * 0.55 or x1 - x0 < width * 0.55 or x1 <= x0 or y1 <= y0:
        return 0, 0, width, height
    page = gray[y0:y1, x0:x1]
    page_h, page_w = page.shape[:2]
    paper = float(np.percentile(page[int(page_h * 0.2) : int(page_h * 0.8), int(page_w * 0.3) : int(page_w * 0.7)], 70))
    limit = paper * 0.78
    x0 += _shadow_depth(page, limit, int(page_w * 0.18))
    if y1 - y0 < height * 0.55 or x1 - x0 < width * 0.55 or x1 <= x0 or y1 <= y0:
        return 0, 0, width, height
    return int(x0), int(y0), int(x1), int(y1)


def _drop_specks(gray: np.ndarray) -> np.ndarray:
    """Apaga grão isolado e preserva traço, ponto e acento."""
    ink = (gray < 150).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if count <= 1:
        return gray
    cleaned = gray.copy()
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area <= 3:
            cleaned[labels == label] = 242
    return cleaned


def _flatten_gray(image: np.ndarray) -> np.ndarray:
    """Aplaina o papel e deixa a tinta escura, no mesmo tamanho."""
    bgr = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    balanced = _neutralize_paper(bgr)
    gray = cv2.cvtColor(balanced, cv2.COLOR_BGR2GRAY)
    short = min(gray.shape[:2])
    sigma = float(np.clip(short * 0.08, 12, 32))
    background = cv2.GaussianBlur(gray, (0, 0), sigma)
    flat = cv2.divide(gray, np.maximum(background, 1), scale=255)
    flat = reduce_bleed_through(flat, 0.5)
    low, high = np.percentile(flat, (1.5, 98.5))
    if high - low > 20:
        flat = np.clip((flat.astype(np.float32) - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
    return _drop_specks(flat)


def _lift_paper(gray: np.ndarray) -> np.ndarray:
    """Leva o grão claro do papel para branco e conserva o traço escuro."""
    levels = np.arange(256, dtype=np.float32)
    weight = np.clip((levels - 145.0) / 70.0, 0.0, 1.0)
    weight = weight * weight * (3.0 - 2.0 * weight)
    lifted = np.clip(levels * (1.0 - weight) + 252.0 * weight, 0, 255).astype(np.uint8)
    return cv2.LUT(gray, lifted)


def prepare_for_reading(image: np.ndarray) -> np.ndarray:
    """Aplaina a página e refina a tinta, no mesmo tamanho das faixas já marcadas."""
    flat = _lift_paper(refine_tiles(_flatten_gray(image)))
    return cv2.cvtColor(flat, cv2.COLOR_GRAY2BGR)


def compose_reading_view(image: np.ndarray, progress=None) -> tuple[np.ndarray, int, int, int]:
    """Melhora a página inteira; aplica a refilagem somente ao final."""
    scale = reading_scale(*image.shape[:2])
    if progress:
        progress("original", image, 0, 0, 1, 0, 0)
    flat = _flatten_gray(image)
    sharp = _blend_tiles(flat, tile=_TILE, overlap=_TILE_OVERLAP,
                         scale=scale if scale > 1 else _TILE_SCALE,
                         keep_size=scale == 1, progress=progress)
    view = _lift_paper(sharp)
    if progress:
        progress("crop", None, 0, 0, scale, 0, 0)
    x0, y0, x1, y1 = refile_window(image)
    view = cv2.cvtColor(view[y0 * scale:y1 * scale, x0 * scale:x1 * scale], cv2.COLOR_GRAY2BGR)
    if progress:
        progress("finished", view, 0, 0, scale, 0, 0)
    return view, int(x0), int(y0), int(scale)


def apply_enhance(image: ImageInput, params: EnhanceParams | None = None) -> np.ndarray:
    """Aplaina o papel, reduz verso/marca d'água e sobe o contraste da tinta."""
    cfg = (params or EnhanceParams()).clamp()
    bgr = load_image(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr

    if cfg.background_sigma > 0:
        background = cv2.GaussianBlur(gray, (0, 0), cfg.background_sigma)
        gray = cv2.divide(gray, np.maximum(background, 1), scale=255)

    gray = reduce_bleed_through(gray, cfg.bleed)

    if abs(cfg.gamma - 1.0) > 0.01:
        lut = np.array(
            [np.clip((i / 255.0) ** cfg.gamma * 255.0, 0, 255) for i in range(256)],
            dtype=np.uint8,
        )
        gray = cv2.LUT(gray, lut)

    gray = cv2.convertScaleAbs(gray, alpha=cfg.contrast, beta=cfg.brightness)

    if cfg.clahe_clip > 0:
        gray = _clahe(gray, clip_limit=cfg.clahe_clip, tile=8)

    if cfg.denoise > 0:
        gray = cv2.fastNlMeansDenoising(
            gray, None, h=float(cfg.denoise), templateWindowSize=7, searchWindowSize=15
        )

    if cfg.unsharp > 0:
        blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
        gray = cv2.addWeighted(gray, 1.0 + cfg.unsharp, blur, -cfg.unsharp, 0)

    return gray
