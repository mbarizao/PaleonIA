"""Pede a leitura de um recorte ao modelo de visão (Ollama ou API compatível)."""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

from paleonia.config import Settings, require_remote_llm
from paleonia.image_enhance.preprocess import png_bytes

_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def extract_after_think(text: str) -> str:
    parts = _THINK_CLOSE.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip()
    if "<think>" in text.lower():
        return ""
    return text.strip()


def parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("A resposta não trouxe JSON.")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("O JSON da leitura não é um objeto.")
    return payload


def _fit_for_model(image: np.ndarray, long_side: int) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= long_side:
        return image
    scale = long_side / longest
    return cv2.resize(
        image,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


_RUNNER_TOKENS = ("model runner", "llama-server", "unexpected eof", "status code: 500", "server closed")
_API_RETRY_TOKENS = ("http 429", "http 500", "http 502", "http 503", "rate limit", "overloaded")
_PAUSE = {"runner": 45.0, "timeout": 20.0, "retry": 2.0}


def _failure_kind(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__} {exc}".lower()
    if any(token in text for token in _RUNNER_TOKENS):
        return "runner"
    if any(token in text for token in _API_RETRY_TOKENS):
        return "timeout"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    name = exc.__class__.__name__.lower()
    if name in {"jsondecodeerror", "responseerror"} or "resposta vazia" in text:
        return "retry"
    return ""


def _wait_until_idle(host: str, limit: float = 120) -> None:
    url = host.rstrip("/") + "/api/ps"
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode())
        except (OSError, ValueError, json.JSONDecodeError):
            return
        if not payload.get("models"):
            return
        time.sleep(5)


def _image_data_url(image: np.ndarray) -> str:
    encoded = base64.b64encode(png_bytes(image)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _text_from_openai(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise RuntimeError("A API não devolveu uma leitura.")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    text = str(content).strip()
    if not text:
        text = extract_after_think(str(message.get("reasoning") or ""))
    return text


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
        raise RuntimeError(f"A API devolveu HTTP {exc.code}: {detail}") from exc


def _ask_openai(settings: Settings, prompt: str, image: np.ndarray) -> dict:
    require_remote_llm(settings)
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://paleonia.local",
        "X-Title": settings.app_name,
    }
    body = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image)}},
                ],
            }
        ],
        "temperature": settings.llm_temperature,
        "top_p": settings.llm_top_p,
        "max_tokens": settings.llm_max_tokens,
    }
    if settings.llm_json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        payload = _post_json(url, body, headers, settings.llm_timeout)
    except RuntimeError as exc:
        if settings.llm_json_mode and exc.args and "HTTP 400" in str(exc) and "response_format" in str(exc).lower():
            body.pop("response_format", None)
            payload = _post_json(url, body, headers, settings.llm_timeout)
        else:
            raise
    text = _text_from_openai(payload)
    if not text:
        raise RuntimeError(f"O modelo {settings.llm_model} devolveu resposta vazia em {settings.llm_base_url}.")
    return parse_json_object(text)


def _ask_ollama(settings: Settings, prompt: str, image: np.ndarray) -> dict:
    from ollama import Client

    client = Client(host=settings.ollama_host, timeout=settings.llm_timeout)
    response = client.chat(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt, "images": [png_bytes(image)]}],
        think=False,
        stream=False,
        format="json",
        options=settings.ollama_options(),
    )
    message = response.message
    text = (message.content or "").strip() or extract_after_think(message.thinking or "")
    if not text:
        raise RuntimeError(f"O modelo {settings.llm_model} devolveu resposta vazia em {settings.ollama_host}.")
    return parse_json_object(text)


def _ask_once(settings: Settings, prompt: str, image: np.ndarray) -> dict:
    if settings.llm_provider == "openai":
        return _ask_openai(settings, prompt, image)
    if settings.llm_provider != "ollama":
        raise ValueError(f"Provedor de leitura desconhecido: {settings.llm_provider}.")
    return _ask_ollama(settings, prompt, image)


def ask(settings: Settings, prompt: str, image: np.ndarray, attempts: int | None = None) -> dict:
    image = _fit_for_model(image, settings.llm_image_long_side)
    attempts = settings.llm_attempts if attempts is None else attempts
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return _ask_once(settings, prompt, image)
        except Exception as exc:
            last = exc
            kind = _failure_kind(exc)
            if not kind or attempt + 1 >= attempts:
                raise
            if kind == "timeout" and settings.llm_provider == "ollama" and settings.ollama_host:
                _wait_until_idle(settings.ollama_host)
            time.sleep(_PAUSE[kind])
    if last:
        raise last
    raise RuntimeError("A leitura não devolveu resposta.")
