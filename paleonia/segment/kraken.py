"""Localiza as linhas do manuscrito com o segmentador blla do Kraken."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from paleonia.config import PROJECT_ROOT, get_settings
from paleonia.image_enhance.preprocess import save_image, to_pil
from paleonia.segment.fragments import drop_fragment_boxes


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _as_points(value) -> list[tuple[float, float]]:
    if value is None:
        return []
    exterior = getattr(value, "exterior", None)
    if exterior is not None:
        value = list(exterior.coords)
    if hasattr(value, "tolist"):
        value = value.tolist()
    points: list[tuple[float, float]] = []
    try:
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                points.append((float(item[0]), float(item[1])))
    except TypeError:
        return []
    return points


def _clip_box(x0: float, y0: float, x1: float, y1: float, width: int, height: int) -> tuple[int, int, int, int]:
    left = int(np.clip(min(x0, x1), 0, width - 1))
    right = int(np.clip(max(x0, x1), left + 1, width))
    top = int(np.clip(min(y0, y1), 0, height - 1))
    bottom = int(np.clip(max(y0, y1), top + 1, height))
    return left, top, right, bottom


def boxes_from_segmentation(segmentation, shape: tuple[int, int]) -> list[list[int]]:
    """Converte as linhas do segmentador blla em caixas [x0, y0, x1, y1]."""
    height, width = shape[:2]
    raw_lines = segmentation.get("lines") if isinstance(segmentation, dict) else getattr(segmentation, "lines", None)
    boxes: list[list[int]] = []
    for line in raw_lines or []:
        if isinstance(line, dict):
            boundary = line.get("boundary")
            baseline = line.get("baseline")
        else:
            boundary = getattr(line, "boundary", None)
            baseline = getattr(line, "baseline", None)
        points = _as_points(boundary)
        from_baseline = False
        if len(points) < 2:
            points = _as_points(baseline)
            from_baseline = True
        if len(points) < 2:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        y0, y1 = min(ys), max(ys)
        if from_baseline or y1 - y0 < 18:
            y0 -= 16
            y1 += 10
        box = list(_clip_box(min(xs) - 6, y0, max(xs) + 6, y1, width, height))
        if box[2] - box[0] < 24 or box[3] - box[1] < 8:
            continue
        if box[3] - box[1] > height * 0.22:
            continue
        boxes.append(box)
    return drop_fragment_boxes(boxes)


def _segment_local(image: np.ndarray, device: str) -> list[list[int]]:
    from kraken import blla

    pil = to_pil(image).convert("RGB")
    segmentation = blla.segment(pil, text_direction="horizontal-lr", device=_resolve_device(device))
    return boxes_from_segmentation(segmentation, image.shape)


def _windows_kraken_python() -> Path | None:
    settings = get_settings()
    candidates = [
        Path(settings.kraken_python) if settings.kraken_python else None,
        PROJECT_ROOT / ".venv-kraken" / "Scripts" / "python.exe",
        Path.home() / ".venv-transcript-kraken" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def _run_segment_command(command: list[str], *, env: dict | None = None) -> list[list[int]]:
    completed = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        timeout=get_settings().kraken_timeout,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "o segmentador não devolveu as linhas")
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    boxes = []
    for item in payload.get("lines") or []:
        box = item.get("box") or []
        if len(box) == 4:
            boxes.append([int(value) for value in box])
    return boxes


def _segment_via_windows(image_path: Path, device: str) -> list[list[int]] | None:
    python = _windows_kraken_python()
    if python is None:
        return None
    env = os.environ.copy()
    root = str(PROJECT_ROOT)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    command = [str(python), "-m", "paleonia.segment", "--image", str(image_path), "--device", device]
    return _run_segment_command(command, env=env)


def segment_line_boxes(
    image: np.ndarray,
    *,
    image_path: str | Path | None = None,
    device: str | None = None,
) -> list[list[int]]:
    """Localiza as linhas com o segmentador neural blla, nas coordenadas da imagem exibida."""
    if device is None:
        device = get_settings().kraken_device
    try:
        import kraken  # noqa: F401

        return _segment_local(image, device)
    except ImportError:
        path = Path(image_path) if image_path else None
        temporary: Path | None = None
        if path is None:
            handle, name = tempfile.mkstemp(suffix=".png")
            os.close(handle)
            temporary = Path(name)
            save_image(image, temporary)
            path = temporary
        try:
            windows = _segment_via_windows(path, device)
            if windows is not None:
                return windows
            raise RuntimeError(
                "O modelo de linhas (Kraken blla) não está instalado neste Python. "
                "Defina KRAKEN_PYTHON com o python.exe do ambiente em que o Kraken foi instalado."
            )
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="paleonia.segment",
        description="Localiza linhas de manuscrito com o Kraken blla",
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--device", default=None)
    args = parser.parse_args(argv)
    image = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"Não foi possível ler {args.image}")
    boxes = _segment_local(image, args.device or get_settings().kraken_device)
    print(json.dumps({"lines": [{"box": box} for box in boxes]}, ensure_ascii=False))
    return 0

