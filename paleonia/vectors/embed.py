"""Vetores de texto pelo Ollama ou por uma API no formato da OpenAI."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from paleonia.config import Settings, get_settings, normalize_host

_BATCH = 16


def vector_literal(values: list[float]) -> str:
    if not values:
        raise ValueError("Vetor vazio.")
    return "[" + ",".join(format(float(value), ".8g") for value in values) + "]"


def parse_ollama_embeddings(payload: dict, expected: int) -> list[list[float]]:
    rows = payload.get("embeddings")
    if rows is None and "embedding" in payload:
        rows = [payload["embedding"]]
    if not isinstance(rows, list) or len(rows) != expected:
        raise RuntimeError("O Ollama não devolveu um vetor para cada texto.")
    return [_as_vector(row) for row in rows]


def parse_openai_embeddings(payload: dict, expected: int) -> list[list[float]]:
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != expected:
        raise RuntimeError("A API de embeddings não devolveu um vetor para cada texto.")
    ordered = sorted(rows, key=lambda item: int(item.get("index") or 0) if isinstance(item, dict) else 0)
    return [_as_vector(item.get("embedding") if isinstance(item, dict) else None) for item in ordered]


def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    if not texts:
        return []
    settings = settings or get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH):
        chunk = texts[start : start + _BATCH]
        if settings.embed_provider == "ollama":
            rows = _embed_ollama(settings, chunk)
        else:
            rows = _embed_openai(settings, chunk)
        _check_dimensions(rows, settings)
        vectors.extend(rows)
    return vectors


def _as_vector(value) -> list[float]:
    if not isinstance(value, list) or not value:
        raise RuntimeError("A resposta de embeddings não trouxe um vetor.")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("A resposta de embeddings trouxe um vetor inválido.") from exc


def _check_dimensions(rows: list[list[float]], settings: Settings) -> None:
    expected = settings.embed_dimensions
    for row in rows:
        if len(row) != expected:
            raise RuntimeError(
                f"O modelo {settings.embed_model} devolveu {len(row)} dimensões; "
                f"EMBED_DIMENSIONS está em {expected}."
            )


def _embed_ollama(settings: Settings, texts: list[str]) -> list[list[float]]:
    host = normalize_host(settings.ollama_host)
    url = host.rstrip("/") + "/api/embed"
    body = {"model": settings.embed_model, "input": texts}
    try:
        payload = _post_json(url, body, {"Content-Type": "application/json"}, settings.embed_timeout)
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            raise RuntimeError(
                f"O modelo de embeddings {settings.embed_model} não está no Ollama. "
                f"Rode: ollama pull {settings.embed_model}"
            ) from exc
        raise
    return parse_ollama_embeddings(payload, len(texts))


def _embed_openai(settings: Settings, texts: list[str]) -> list[list[float]]:
    if not settings.embed_base_url:
        raise ValueError("Defina EMBED_BASE_URL ou LLM_BASE_URL para gerar os vetores.")
    if not settings.embed_api_key:
        raise ValueError("Defina EMBED_API_KEY ou LLM_API_KEY para gerar os vetores.")
    url = settings.embed_base_url.rstrip("/") + "/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.embed_api_key}",
        "Content-Type": "application/json",
    }
    body = {"model": settings.embed_model, "input": texts, "dimensions": settings.embed_dimensions}
    payload = _post_json(url, body, headers, settings.embed_timeout)
    return parse_openai_embeddings(payload, len(texts))


def _post_json(url: str, body: dict, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip().replace("\n", " ")
        if len(detail) > 400:
            detail = detail[:400]
        raise RuntimeError(f"A API de embeddings devolveu HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Não foi possível gerar os vetores: {exc}") from exc
