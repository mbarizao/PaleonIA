"""Tira da transcrição marcas que não são linha: borrão no vão, ponto, fiapo."""
from __future__ import annotations


def drop_fragment_boxes(boxes: list[list[int]]) -> list[list[int]]:
    flags = keep_line_boxes(boxes)
    return [box for box, keep in zip(boxes, flags) if keep]


def keep_line_boxes(boxes: list[list[int]]) -> list[bool]:
    """Uma faixa estreita no vão entre os textos sai. Uma palavra curta dentro da coluna fica."""
    if len(boxes) < 8:
        return [True] * len(boxes)
    widths = sorted(int(box[2]) - int(box[0]) for box in boxes)
    median = widths[len(widths) // 2]
    limit = max(48, int(median * 0.15))
    real = [box for box in boxes if int(box[2]) - int(box[0]) >= limit]
    flags: list[bool] = []
    for box in boxes:
        width = int(box[2]) - int(box[0])
        if width >= limit:
            flags.append(True)
            continue
        overlaps = 0
        for other in real:
            shared = min(int(box[2]), int(other[2])) - max(int(box[0]), int(other[0]))
            if shared > width * 0.5:
                overlaps += 1
                if overlaps >= 2:
                    break
        flags.append(overlaps >= 2)
    if sum(flags) < 4:
        return [True] * len(boxes)
    return flags
