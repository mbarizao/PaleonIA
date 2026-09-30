"""Precedentes de linhas já conferidas para a leitura seguinte."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

_GAP = re.compile(r"\[ileg[ií]vel\]", re.IGNORECASE)
_TOKEN = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_SKIP = frozenset(
    {
        "ilegivel",
        "ilegível",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "na",
        "no",
        "nas",
        "nos",
        "a",
        "o",
        "as",
        "os",
        "e",
        "ou",
        "um",
        "uma",
        "que",
        "por",
        "para",
        "com",
        "sem",
        "ao",
        "aos",
        "se",
        "sua",
        "seu",
        "não",
        "nao",
    }
)

MIN_SCORE = 0.55
MAX_NEIGHBORS = 4
MIN_QUERY_CHARS = 8
MAX_FORMS = 40
MIN_FORM_COUNT = 3


def has_gap(text: str) -> bool:
    return bool(_GAP.search(text or ""))


def gap_query(text: str) -> str:
    """Tira o vão e deixa o fraseado que ainda se lê."""
    cleaned = _GAP.sub(" ", text or "")
    return " ".join(cleaned.split())


def forms_from_texts(
    texts: list[str],
    *,
    min_count: int = MIN_FORM_COUNT,
    limit: int = MAX_FORMS,
) -> list[str]:
    """Formas que se repetem em linhas diferentes, as mais frequentes primeiro."""
    counts: Counter[str] = Counter()
    for text in texts:
        seen: set[str] = set()
        for token in _TOKEN.findall(gap_query(text)):
            if len(token) < 2 or len(token) > 40:
                continue
            if token.casefold() in _SKIP:
                continue
            seen.add(token)
        counts.update(seen)
    ranked = sorted(
        ((count, token) for token, count in counts.items() if count >= min_count),
        key=lambda item: (-item[0], item[1]),
    )
    return [token for _, token in ranked[:limit]]


def neighbor_texts(hits: list[dict], *, min_score: float = MIN_SCORE, limit: int = MAX_NEIGHBORS) -> list[str]:
    found: list[str] = []
    for hit in hits:
        text = " ".join(str(hit.get("text") or "").split())
        if not text or float(hit.get("score") or 0) < min_score or text in found:
            continue
        found.append(text[:400])
        if len(found) >= limit:
            break
    return found


def revise_gap_texts(
    texts: list[str],
    *,
    lookup: Callable[[str], list[str]],
    reread: Callable[[list[str]], list[str]],
) -> list[str]:
    """Segunda leitura só das linhas com [ilegível], se houver precedente próximo."""
    gapped = [index for index, text in enumerate(texts) if has_gap(text)]
    if not gapped:
        return texts
    neighbors: list[str] = []
    for index in gapped:
        query = gap_query(texts[index])
        if len(query) < MIN_QUERY_CHARS:
            continue
        try:
            found = lookup(query)
        except Exception:
            continue
        for item in found:
            cleaned = " ".join(str(item).split())
            if not cleaned or cleaned in neighbors:
                continue
            neighbors.append(cleaned[:400])
            if len(neighbors) >= MAX_NEIGHBORS:
                break
        if len(neighbors) >= MAX_NEIGHBORS:
            break
    if not neighbors:
        return texts
    try:
        revised = reread(neighbors)
    except Exception:
        return texts
    if len(revised) < len(texts):
        return texts
    merged = list(texts)
    for index in gapped:
        if revised[index].strip():
            merged[index] = revised[index]
    return merged
