from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Union

import cv2
import numpy as np
from PIL import Image

ImageInput = Union[str, Path, bytes, np.ndarray, Image.Image]

_MIN_SHORT_SIDE = 1400
_MAX_SHORT_SIDE = 1800


def load_image(image: ImageInput, *, invalid: str | None = None) -> np.ndarray:
    """Carrega a imagem em BGR (OpenCV)."""
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.is_file():
            raise FileNotFoundError(f"Imagem não encontrada: {path}")
        data = path.read_bytes()
        return _decode_bytes(data, source=str(path), invalid=invalid)

    if isinstance(image, bytes):
        return _decode_bytes(image, source="bytes", invalid=invalid)

    if isinstance(image, Image.Image):
        rgb = np.array(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    if isinstance(image, np.ndarray):
        if image.size == 0:
            raise ValueError("Array de imagem vazio.")
        return image.copy()

    raise TypeError(f"Tipo de imagem não suportado: {type(image)!r}")


def _decode_bytes(data: bytes, source: str, invalid: str | None = None) -> np.ndarray:
    buffer = np.frombuffer(data, dtype=np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError(invalid or f"Não foi possível decodificar a imagem ({source}).")
    return decoded


def encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Falha ao codificar PNG.")
    return encoded.tobytes()


def encode_jpeg(image: np.ndarray, quality: int | None = None) -> bytes:
    from paleonia.config import get_settings

    level = get_settings().jpeg_quality if quality is None else quality
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(level)])
    if not ok:
        raise ValueError("Não foi possível gravar a imagem tratada.")
    return encoded.tobytes()


def save_image(image: np.ndarray, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encode_png(image))
    return destination


def enhance_document(image: ImageInput) -> np.ndarray:
    """Atalho com parâmetros padrão; o fluxo híbrido usa EnhanceParams da IA."""
    from paleonia.image_enhance.enhance import apply_enhance

    bgr = load_image(image)
    gray = apply_enhance(bgr)
    return _resize_for_reading(gray)


def _resize_for_reading(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape[:2]
    short_side = min(height, width)
    if short_side < _MIN_SHORT_SIDE:
        scale = _MIN_SHORT_SIDE / short_side
        interpolation = cv2.INTER_CUBIC
    elif short_side > _MAX_SHORT_SIDE:
        scale = _MAX_SHORT_SIDE / short_side
        interpolation = cv2.INTER_AREA
    else:
        return gray

    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(gray, new_size, interpolation=interpolation)


def _clahe(gray: np.ndarray, clip_limit: float, tile: int) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile, tile))
    return clahe.apply(gray)


def to_pil(image: np.ndarray) -> Image.Image:
    if image.ndim == 2:
        return Image.fromarray(image, mode="L")
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def png_bytes(image: np.ndarray) -> bytes:
    pil = to_pil(image)
    buffer = BytesIO()
    pil.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
