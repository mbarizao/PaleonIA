"""Conexão com o Postgres do PaleonIA."""
from __future__ import annotations


def connect(database_url: str):
    import psycopg

    try:
        return psycopg.connect(database_url, connect_timeout=5)
    except psycopg.Error as exc:
        raise ConnectionError(safe_message(exc)) from exc


def safe_message(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()
    if "://" in text or "password" in lowered or "database_url" in lowered:
        return "Não foi possível usar o Postgres. Confira DATABASE_URL e se o serviço está no ar."
    if "extension" in lowered and "vector" in lowered:
        return "O Postgres não tem a extensão pgvector. Use a imagem pgvector/pgvector ou instale a extensão."
    return text
