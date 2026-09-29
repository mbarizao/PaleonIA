from __future__ import annotations

import json
import re
import threading
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from paleonia.config import IMAGE_MAX_PIXELS, get_settings, limit_text
from paleonia.enhance import compose_reading_view
from paleonia.preprocess import encode_jpeg, load_image
from paleonia.segment import segment_line_boxes

PAGE_ID_RE = re.compile(r"^p\d{3,6}$")
ITEM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")

# D segue a ordem de leitura: numa página, de cima para baixo;
# num livro aberto, a página esquerda inteira e depois a direita.
# T só numera as partes marcadas para entrar na transcrição.


def _reading_column(lines: list[dict]) -> dict[str, int]:
    if len(lines) < 4:
        return {line["id"]: 0 for line in lines}
    ordered = sorted(lines, key=lambda line: (line["box"][0] + line["box"][2]) / 2)
    best_gap = 0
    split_after = None
    for index in range(len(ordered) - 1):
        left = ordered[index]["box"]
        right = ordered[index + 1]["box"]
        gap = int(right[0]) - int(left[2])
        left_count = index + 1
        right_count = len(ordered) - left_count
        if gap >= 40 and left_count >= 2 and right_count >= 2 and gap > best_gap:
            best_gap = gap
            split_after = index
    if split_after is None:
        return {line["id"]: 0 for line in lines}
    return {line["id"]: 0 if index <= split_after else 1 for index, line in enumerate(ordered)}


def annotate_lines(lines: list[dict]) -> list[dict]:
    columns = _reading_column(lines)
    ordered = sorted(
        lines,
        key=lambda line: (
            columns.get(line["id"], 0),
            int(line["box"][1]),
            int(line["box"][0]),
            str(line["id"]),
        ),
    )
    transcript = 0
    annotated: list[dict] = []
    for doc_index, line in enumerate(ordered, start=1):
        include = bool(line.get("include", True))
        parts_in = list(line.get("parts") or [])
        parts: list[dict] = []
        for part_index, part in enumerate(parts_in, start=1):
            record = {
                "id": part["id"],
                "text": part.get("text") or "",
                "parte": part_index,
                "linha_transcrita": None,
            }
            if include:
                transcript += 1
                record["linha_transcrita"] = transcript
            parts.append(record)
        annotated.append(
            {
                "id": line["id"],
                "box": [int(value) for value in line["box"][:4]],
                "include": include,
                "linha_documento": doc_index,
                "parts": parts,
            }
        )
    return annotated


def _new_id(prefix: str) -> str:
    import secrets

    return f"{prefix}_{secrets.token_hex(4)}"


def _line_from_box(box: list[int]) -> dict:
    return {
        "id": _new_id("ln"),
        "box": [int(value) for value in box],
        "include": True,
        "parts": [{"id": _new_id("pt"), "text": ""}],
    }


def _copy_line(line: dict) -> dict:
    return {
        "id": line["id"],
        "box": [int(value) for value in line["box"][:4]],
        "include": bool(line.get("include", True)),
        "parts": [{"id": part["id"], "text": part.get("text") or ""} for part in line.get("parts") or []],
    }


def _y_overlap(a: list[int], b: list[int]) -> float:
    top = max(a[1], b[1])
    bottom = min(a[3], b[3])
    inter = max(0, bottom - top)
    base = max(1, min(a[3] - a[1], b[3] - b[1]))
    return inter / base


def _apply_boxes(old_lines: list[dict], boxes: list[list[int]]) -> list[dict]:
    """Casa faixas novas com as antigas para não perder o texto já digitado."""
    unused = [_copy_line(line) for line in old_lines]
    result: list[dict] = []
    for box in boxes:
        best_index = None
        best_score = 0.4
        for index, old in enumerate(unused):
            score = _y_overlap(box, old["box"])
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is None:
            result.append(_line_from_box(box))
            continue
        matched = unused.pop(best_index)
        matched["box"] = [int(value) for value in box]
        if matched["include"] and not matched["parts"]:
            matched["parts"] = [{"id": _new_id("pt"), "text": ""}]
        result.append(matched)
    for old in unused:
        if any((part.get("text") or "").strip() for part in old["parts"]):
            result.append(old)
    return result


def _shift_box(box: list[int], dx: int, dy: int, width: int, height: int) -> list[int]:
    x0 = int(np.clip(int(box[0]) - dx, 0, max(0, width - 1)))
    y0 = int(np.clip(int(box[1]) - dy, 0, max(0, height - 1)))
    x1 = int(np.clip(int(box[2]) - dx, x0 + 1, width))
    y1 = int(np.clip(int(box[3]) - dy, y0 + 1, height))
    return [x0, y0, x1, y1]


def _clamp_sensitivity(value: float) -> float:
    return float(min(0.9, max(0.15, float(value))))


def normalize_image(data: bytes) -> tuple[bytes, int, int]:
    """Aplica a orientação EXIF e grava JPEG, para a caixa bater com o que o navegador mostra."""
    settings = get_settings()
    Image.MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS
    try:
        with Image.open(BytesIO(data)) as incoming:
            image = ImageOps.exif_transpose(incoming)
            if image is None:
                raise ValueError("Não foi possível ler a imagem. Use JPG ou PNG.")
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            if min(image.size) < 32:
                raise ValueError("Imagem pequena demais.")
            if max(image.size) > settings.max_image_side:
                side = settings.max_image_side
                image.thumbnail((side, side), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=settings.jpeg_quality)
            return buffer.getvalue(), image.width, image.height
    except UnidentifiedImageError as exc:
        raise ValueError("Não foi possível ler a imagem. Use JPG ou PNG.") from exc


def _clean_lines(raw: list[dict], width: int, height: int) -> list[dict]:
    cleaned: list[dict] = []
    seen_lines: set[str] = set()
    seen_parts: set[str] = set()
    for item in raw:
        line_id = str(item.get("id") or "")
        if not ITEM_ID_RE.fullmatch(line_id) or line_id in seen_lines:
            raise ValueError(f"Identificador de linha inválido: {line_id}")
        seen_lines.add(line_id)
        box = _clamp_box(item.get("box"), width, height)
        include = bool(item.get("include", True))
        parts: list[dict] = []
        for part in item.get("parts") or []:
            part_id = str(part.get("id") or "")
            if not ITEM_ID_RE.fullmatch(part_id) or part_id in seen_parts:
                raise ValueError(f"Identificador de transcrição inválido: {part_id}")
            seen_parts.add(part_id)
            parts.append({"id": part_id, "text": limit_text(str(part.get("text") or ""))})
        if include and not parts:
            parts.append({"id": _new_id("pt"), "text": ""})
        cleaned.append({"id": line_id, "box": box, "include": include, "parts": parts})
    return cleaned


def _clamp_box(box, width: int, height: int) -> list[int]:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError("Cada linha do documento precisa de uma caixa com 4 valores.")
    x0, y0, x1, y1 = [int(round(float(value))) for value in box]
    x0 = max(0, min(width - 2, x0))
    y0 = max(0, min(height - 2, y0))
    x1 = max(x0 + 2, min(width, x1))
    y1 = max(y0 + 2, min(height, y1))
    return [x0, y0, x1, y1]


class DeskStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.images = self.root / "images"
        self.images.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "session.json"
        if self.path.is_file():
            self.session = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.session = {"pages": []}
        self.session.setdefault("pages", [])
        self._lock = threading.Lock()

    def add_page(self, filename: str, data: bytes, sensitivity: float | None = None) -> dict:
        jpeg, _width, _height = normalize_image(data)
        page_id = self._next_page_id()
        image_path = self.images / f"{page_id}.jpg"
        original_path = self.images / f"{page_id}.original.jpg"
        decoded = load_image(jpeg, invalid="Não foi possível ler a imagem. Use JPG ou PNG.")
        view, origin_x, origin_y = compose_reading_view(decoded)
        height, width = view.shape[:2]
        image_path.write_bytes(encode_jpeg(view))
        original_path.write_bytes(jpeg)
        level = _clamp_sensitivity(get_settings().default_sensitivity if sensitivity is None else sensitivity)
        try:
            boxes = segment_line_boxes(view, image_path=image_path)
        except Exception:
            image_path.unlink(missing_ok=True)
            original_path.unlink(missing_ok=True)
            raise
        page = {
            "id": page_id,
            "filename": _safe_name(filename),
            "width": int(width),
            "height": int(height),
            "original_width": int(decoded.shape[1]),
            "original_height": int(decoded.shape[0]),
            "crop_origin": [int(origin_x), int(origin_y)],
            "prepared": True,
            "sensitivity": level,
            "lines": [_line_from_box(box) for box in boxes],
        }
        self.session["pages"].append(page)
        self._save()
        return self.public_page(page)

    def replace_lines(self, page_id: str, lines: list[dict], sensitivity: float | None = None) -> dict:
        page = self._require(page_id)
        page["lines"] = _clean_lines(lines, int(page["width"]), int(page["height"]))
        if sensitivity is not None:
            page["sensitivity"] = _clamp_sensitivity(sensitivity)
        self._save()
        return self.public_page(page)

    def set_line_texts(self, page_id: str, texts: dict[str, str], *, only_empty: bool = True) -> dict:
        """Grava a leitura automática na primeira parte de cada linha, sem apagar correção já feita."""
        with self._lock:
            page = self._require(page_id)
            for line in page["lines"]:
                if line["id"] not in texts:
                    continue
                if only_empty and any((part.get("text") or "").strip() for part in line.get("parts") or []):
                    continue
                text = limit_text(texts[line["id"]])
                if not line.get("parts"):
                    line["parts"] = [{"id": _new_id("pt"), "text": text}]
                else:
                    line["parts"][0]["text"] = text
            self._save()
            return self.public_page(page)

    def redetect(self, page_id: str, sensitivity: float | None = None) -> dict:
        page = self._require(page_id)
        path = self.require_image(page_id)
        decoded = load_image(path, invalid="Não foi possível reler a imagem da página.")
        level = _clamp_sensitivity(get_settings().default_sensitivity if sensitivity is None else sensitivity)
        boxes = segment_line_boxes(decoded, image_path=path)
        page["lines"] = _apply_boxes(page["lines"], boxes)
        page["sensitivity"] = level
        self._save()
        return self.public_page(page)

    def delete_page(self, page_id: str) -> None:
        self._require(page_id)
        self.session["pages"] = [page for page in self.session["pages"] if page["id"] != page_id]
        path = self.images / f"{page_id}.jpg"
        if path.is_file():
            path.unlink()
        self._save()

    def image_path(self, page_id: str) -> Path | None:
        if not PAGE_ID_RE.fullmatch(page_id):
            return None
        path = (self.images / f"{page_id}.jpg").resolve()
        if path.parent != self.images.resolve() or not path.is_file():
            return None
        return path

    def require_image(self, page_id: str) -> Path:
        path = self.image_path(page_id)
        if path is None:
            raise FileNotFoundError(f"Imagem da página {page_id} não encontrada")
        return path

    def original_path(self, page_id: str) -> Path | None:
        if not PAGE_ID_RE.fullmatch(page_id):
            return None
        path = (self.images / f"{page_id}.original.jpg").resolve()
        if path.parent != self.images.resolve() or not path.is_file():
            return self.image_path(page_id)
        return path

    def ensure_prepared(self, page_id: str) -> dict:
        """Grava a imagem tratada no lugar da página e desloca as faixas junto com o corte."""
        page = self._require(page_id)
        if page.get("prepared"):
            return page
        current = self.require_image(page_id)
        original = self.images / f"{page_id}.original.jpg"
        if not original.is_file():
            original.write_bytes(current.read_bytes())
        decoded = load_image(original, invalid="Não foi possível reler a imagem da página.")
        view, origin_x, origin_y = compose_reading_view(decoded)
        height, width = view.shape[:2]
        current.write_bytes(encode_jpeg(view))
        page["width"] = int(width)
        page["height"] = int(height)
        page["original_width"] = int(decoded.shape[1])
        page["original_height"] = int(decoded.shape[0])
        page["crop_origin"] = [int(origin_x), int(origin_y)]
        page["prepared"] = True
        page["lines"] = [
            {
                **line,
                "box": _shift_box(line["box"], origin_x, origin_y, width, height),
            }
            for line in page.get("lines") or []
        ]
        self._save()
        return page

    def public_session(self) -> dict:
        pages = []
        for page in self.session["pages"]:
            if self.image_path(page["id"]) is not None:
                self.ensure_prepared(page["id"])
            pages.append(self.public_page(page))
        settings = get_settings()
        return {
            "app_name": settings.app_name,
            "default_sensitivity": settings.default_sensitivity,
            "reader": settings.reader_label(),
            "work_dir": str(self.root),
            "pages": pages,
        }

    def public_page(self, page: dict) -> dict:
        path = self.image_path(page["id"])
        stamp = int(path.stat().st_mtime) if path is not None else 0
        origin = page.get("crop_origin") or [0, 0]
        return {
            "id": page["id"],
            "filename": page["filename"],
            "width": int(page["width"]),
            "height": int(page["height"]),
            "original_width": int(page.get("original_width") or page["width"]),
            "original_height": int(page.get("original_height") or page["height"]),
            "crop_origin": [int(origin[0]), int(origin[1])],
            "prepared": bool(page.get("prepared")),
            "sensitivity": float(page.get("sensitivity") or get_settings().default_sensitivity),
            "image_url": f"/images/{page['id']}?v={stamp}",
            "original_url": f"/images/{page['id']}/original?v={stamp}",
            "lines": annotate_lines(page.get("lines") or []),
        }

    def export_document(self) -> dict:
        pages = []
        for page in self.session["pages"]:
            transcribed = []
            omitted = []
            for line in annotate_lines(page.get("lines") or []):
                if not line["include"]:
                    omitted.append(
                        {
                            "linha_documento": line["linha_documento"],
                            "caixa": line["box"],
                            "texto_guardado": " / ".join(
                                part["text"] for part in line["parts"] if part["text"].strip()
                            ),
                        }
                    )
                    continue
                for part in line["parts"]:
                    transcribed.append(
                        {
                            "linha_transcrita": part["linha_transcrita"],
                            "linha_documento": line["linha_documento"],
                            "parte": part["parte"],
                            "texto": part["text"],
                            "caixa": line["box"],
                            "id_linha_documento": line["id"],
                            "id_linha_transcrita": part["id"],
                        }
                    )
            pages.append(
                {
                    "arquivo": page["filename"],
                    "largura": int(page["width"]),
                    "altura": int(page["height"]),
                    "linhas": transcribed,
                    "linhas_documento_sem_transcricao": omitted,
                }
            )
        return {"paginas": pages}

    def export_text(self) -> str:
        chunks = ["T = linha transcrita. D = linha no documento.", ""]
        pages = self.session["pages"]
        if not pages:
            chunks.append("Nenhuma página importada.")
            return "\n".join(chunks) + "\n"
        for page in pages:
            chunks.append(f"# {page['filename']}")
            omitted: list[str] = []
            for line in annotate_lines(page.get("lines") or []):
                label = f"D{line['linha_documento']:03d}"
                if not line["include"]:
                    omitted.append(label)
                    continue
                written = [part for part in line["parts"] if (part.get("text") or "").strip()]
                several = len(line["parts"]) > 1
                for part in written:
                    parte = f" parte {part['parte']}" if several else ""
                    text = part["text"].replace("\r\n", "\n").replace("\n", " / ").strip()
                    number = part["linha_transcrita"] or 0
                    chunks.append(f"[T{number:03d} | {label}{parte}] {text}")
            if omitted:
                chunks.append("Fora da transcrição: " + ", ".join(omitted))
            chunks.append("")
        return "\n".join(chunks).rstrip() + "\n"

    def _require(self, page_id: str) -> dict:
        if not PAGE_ID_RE.fullmatch(page_id):
            raise FileNotFoundError(f"Página {page_id} não encontrada")
        for page in self.session["pages"]:
            if page["id"] == page_id:
                return page
        raise FileNotFoundError(f"Página {page_id} não encontrada")

    def _next_page_id(self) -> str:
        existing = {page["id"] for page in self.session["pages"]}
        number = 1
        while True:
            page_id = f"p{number:03d}"
            if page_id not in existing:
                return page_id
            number += 1

    def _save(self) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.session, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def _safe_name(filename: str) -> str:
    name = Path(filename or "manuscrito.jpg").name.replace("\x00", "").strip()
    return (name or "manuscrito.jpg")[:180]
