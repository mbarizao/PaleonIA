"""Configuração do PaleonIA, lida do ambiente e do arquivo .env na raiz do projeto."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_MAX_PIXELS = 300_000_000

_ENV_LOADED = False
_SETTINGS: Settings | None = None
_READING: Settings | None = None


def load_env() -> None:
    """Carrega `.env` uma vez. Variáveis já definidas no ambiente prevalecem."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _raw(name: str) -> str:
    return os.getenv(name, "").strip()


def _env_str(name: str, default: str) -> str:
    return _raw(name) or default


def _env_int(name: str, default: int) -> int:
    raw = _raw(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} precisa ser um número inteiro, recebeu {raw!r}.") from exc


def _env_float(name: str, default: float) -> float:
    raw = _raw(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} precisa ser um número, recebeu {raw!r}.") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = _raw(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "sim"}


def _first_raw(*names: str) -> str:
    for name in names:
        value = _raw(name)
        if value:
            return value
    return ""


def _env_float_first(names: tuple[str, ...], default: float) -> float:
    for name in names:
        if _raw(name):
            return _env_float(name, default)
    return default


def _env_int_first(names: tuple[str, ...], default: int) -> int:
    for name in names:
        if _raw(name):
            return _env_int(name, default)
    return default


def _env_path(name: str, default: str) -> Path:
    raw = _env_str(name, default)
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def normalize_host(value: str) -> str:
    host = value.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


def export_stem(app_name: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in app_name).strip("-")
    return slug or "paleonia"


@dataclass(frozen=True)
class Settings:
    app_name: str = "PaleonIA"
    app_version: str = "1.0.0"
    web_host: str = "127.0.0.1"
    web_port: int = 8878
    work_dir: Path = PROJECT_ROOT / "output" / "desk"
    open_browser: bool = True
    auth_username: str = "paleonia"
    auth_password: str = ""
    auth_secret: str = ""

    llm_provider: str = "ollama"
    llm_model: str = "qwen3-vl:8b-instruct"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_json_mode: bool = True
    llm_timeout: float = 900
    llm_temperature: float = 0.1
    llm_top_p: float = 0.85
    llm_num_ctx: int = 4096
    llm_max_tokens: int = 1600
    llm_image_long_side: int = 1600
    llm_attempts: int = 2
    ollama_host: str = "http://127.0.0.1:11434"

    kraken_device: str = "auto"
    kraken_python: str = ""
    kraken_timeout: float = 600

    jpeg_quality: int = 93
    default_sensitivity: float = 0.55
    max_image_side: int = 12000
    max_text_chars: int = 20000
    read_group_max_height: int = 520
    read_group_max_count: int = 8

    database_url: str = ""
    embed_provider: str = "ollama"
    embed_model: str = "nomic-embed-text"
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_dimensions: int = 768
    embed_timeout: float = 60.0

    @property
    def download_stem(self) -> str:
        return export_stem(self.app_name)

    def ollama_options(self) -> dict:
        return {
            "temperature": self.llm_temperature,
            "top_p": self.llm_top_p,
            "num_ctx": self.llm_num_ctx,
            "num_predict": self.llm_max_tokens,
        }

    def reader_label(self) -> str:
        if self.llm_provider == "ollama":
            return f"Ollama · {self.llm_model}"
        if "openrouter.ai" in self.llm_base_url:
            origin = "OpenRouter"
        else:
            origin = "API"
        return f"{origin} · {self.llm_model}"


_PROVIDER_ALIASES = {
    "ollama": "ollama",
    "openai": "openai",
    "openrouter": "openai",
    "compatible": "openai",
    "api": "openai",
}


def _llm_choice() -> tuple[str, str, str]:
    """Devolve o protocolo (ollama ou openai), o modelo e a URL base."""
    requested = _env_str("LLM_PROVIDER", "ollama").lower()
    provider = _PROVIDER_ALIASES.get(requested)
    if provider is None:
        raise ValueError(
            "LLM_PROVIDER deve ser ollama, openai ou openrouter, "
            f"recebeu {requested!r}."
        )
    base = _raw("LLM_BASE_URL").rstrip("/")
    if not base and requested == "openrouter":
        base = "https://openrouter.ai/api/v1"
    if provider == "ollama":
        model = _first_raw("LLM_MODEL", "OLLAMA_MODEL") or "qwen3-vl:8b-instruct"
    else:
        model = _raw("LLM_MODEL") or "qwen/qwen3-vl-8b-instruct"
    return provider, model, base


def _embed_choice(llm_provider: str, llm_base_url: str) -> tuple[str, str, str, int, str]:
    requested = (_raw("EMBED_PROVIDER") or ("ollama" if llm_provider == "ollama" else "openai")).lower()
    if requested not in {"ollama", "openai", "openrouter"}:
        raise ValueError(
            "EMBED_PROVIDER deve ser ollama, openai ou openrouter, "
            f"recebeu {requested!r}."
        )
    provider = "ollama" if requested == "ollama" else "openai"
    if provider == "ollama":
        model = _raw("EMBED_MODEL") or "nomic-embed-text"
        dimensions = _env_int("EMBED_DIMENSIONS", 768)
        base = ""
        key = ""
    else:
        model = _raw("EMBED_MODEL") or "text-embedding-3-small"
        dimensions = _env_int("EMBED_DIMENSIONS", 768)
        base = (_raw("EMBED_BASE_URL") or llm_base_url).rstrip("/")
        key = _raw("EMBED_API_KEY") or _raw("LLM_API_KEY")
    if not 1 <= dimensions <= 4096:
        raise ValueError("EMBED_DIMENSIONS precisa ficar entre 1 e 4096.")
    return provider, model, base, dimensions, key


def _build_settings() -> Settings:
    load_env()
    provider, model, base_url = _llm_choice()
    embed_provider, embed_model, embed_base_url, embed_dimensions, embed_api_key = _embed_choice(provider, base_url)
    return Settings(
        app_name=_env_str("APP_NAME", "PaleonIA"),
        app_version=_env_str("APP_VERSION", "1.0.0"),
        web_host=_env_str("PALEONIA_HOST", "127.0.0.1"),
        web_port=_env_int("PALEONIA_PORT", 8878),
        work_dir=_env_path("PALEONIA_WORK_DIR", "output/desk"),
        open_browser=_env_bool("PALEONIA_OPEN_BROWSER", True),
        auth_username=_env_str("AUTH_USERNAME", "admin"),
        auth_password=_raw("AUTH_PASSWORD"),
        auth_secret=_raw("AUTH_SECRET"),
        llm_provider=provider,
        llm_model=model,
        llm_base_url=base_url,
        llm_api_key=_raw("LLM_API_KEY"),
        llm_json_mode=_env_bool("LLM_JSON_MODE", True),
        llm_timeout=_env_float_first(("LLM_TIMEOUT", "OLLAMA_TIMEOUT"), 900),
        llm_temperature=_env_float_first(("LLM_TEMPERATURE", "OLLAMA_TEMPERATURE"), 0.1),
        llm_top_p=_env_float_first(("LLM_TOP_P", "OLLAMA_TOP_P"), 0.85),
        llm_num_ctx=_env_int_first(("LLM_NUM_CTX", "OLLAMA_NUM_CTX"), 4096),
        llm_max_tokens=_env_int_first(("LLM_MAX_TOKENS", "OLLAMA_NUM_PREDICT"), 1600),
        llm_image_long_side=_env_int_first(("LLM_IMAGE_LONG_SIDE", "OLLAMA_IMAGE_LONG_SIDE"), 1600),
        llm_attempts=_env_int_first(("LLM_ATTEMPTS", "OLLAMA_ATTEMPTS"), 2),
        ollama_host=normalize_host(_raw("OLLAMA_HOST") or "http://127.0.0.1:11434"),
        kraken_device=_env_str("KRAKEN_DEVICE", "auto"),
        kraken_python=_raw("KRAKEN_PYTHON"),
        kraken_timeout=_env_float("KRAKEN_TIMEOUT", 600),
        jpeg_quality=_env_int("JPEG_QUALITY", 93),
        default_sensitivity=_env_float("DEFAULT_SENSITIVITY", 0.55),
        max_image_side=_env_int("MAX_IMAGE_SIDE", 12000),
        max_text_chars=_env_int("MAX_TEXT_CHARS", 20000),
        read_group_max_height=_env_int("READ_GROUP_MAX_HEIGHT", 520),
        read_group_max_count=_env_int("READ_GROUP_MAX_COUNT", 8),
        database_url=_raw("DATABASE_URL"),
        embed_provider=embed_provider,
        embed_model=embed_model,
        embed_base_url=embed_base_url,
        embed_api_key=embed_api_key,
        embed_dimensions=embed_dimensions,
        embed_timeout=_env_float("EMBED_TIMEOUT", 60),
    )


def get_settings() -> Settings:
    """Configuração do processo, sem contactar o Ollama."""
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = _build_settings()
    return _SETTINGS


def limit_text(text: str) -> str:
    limit = get_settings().max_text_chars
    return text if len(text) <= limit else text[:limit]


def require_remote_llm(settings: Settings) -> None:
    """Garante URL e chave antes de chamar uma API compatível com a OpenAI."""
    if not settings.llm_base_url:
        raise ValueError(
            "Defina LLM_BASE_URL. Para a OpenRouter use https://openrouter.ai/api/v1 "
            "ou LLM_PROVIDER=openrouter."
        )
    if not settings.llm_api_key:
        raise ValueError("Defina LLM_API_KEY com a chave do provedor.")


def reading_settings() -> Settings:
    """Configuração pronta para ler. Com API remota, exige URL e chave."""
    global _READING
    if _READING is None:
        base = get_settings()
        if base.llm_provider != "ollama":
            require_remote_llm(base)
        _READING = base
    return _READING


def load_settings(
    host: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> Settings:
    base = reading_settings()
    updates: dict = {}
    if host:
        updates["ollama_host"] = normalize_host(host)
    if model:
        updates["llm_model"] = model.strip()
    if timeout is not None:
        updates["llm_timeout"] = float(timeout)
    return replace(base, **updates) if updates else base
