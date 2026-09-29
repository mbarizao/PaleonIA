from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from paleonia.preprocess import ImageInput, load_image, _clahe


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


def prepare_for_reading(image: np.ndarray) -> np.ndarray:
    """Prepara a página para a leitura, no mesmo tamanho das faixas já marcadas."""
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

    flat = _drop_specks(flat)
    flat = cv2.bilateralFilter(flat, d=5, sigmaColor=16, sigmaSpace=3)
    return cv2.cvtColor(flat, cv2.COLOR_GRAY2BGR)


def compose_reading_view(image: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Imagem tratada e a origem (x, y) que foi cortada da moldura."""
    enhanced = prepare_for_reading(image)
    x0, y0, x1, y1 = dark_border_window(enhanced)
    return enhanced[y0:y1, x0:x1].copy(), x0, y0


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
