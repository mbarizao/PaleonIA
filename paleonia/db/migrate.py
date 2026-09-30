"""Aplica os arquivos SQL de paleonia/db/migrations em ordem."""
from __future__ import annotations

from pathlib import Path

from paleonia.db.connect import connect

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
EMBEDDING_DIMENSIONS = 768


def migration_files() -> list[Path]:
    return sorted(path for path in MIGRATIONS.glob("*.sql") if path.is_file())


def sql_statements(script: str) -> list[str]:
    """Separa comandos SQL, respeitando textos, comentários e blocos $$."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    length = len(script)
    while i < length:
        if script.startswith("--", i):
            end = script.find("\n", i)
            i = length if end < 0 else end + 1
            continue
        if script.startswith("/*", i):
            end = script.find("*/", i + 2)
            i = length if end < 0 else end + 2
            continue
        if script[i] == "'":
            buf.append(script[i])
            i += 1
            while i < length:
                buf.append(script[i])
                if script[i] == "'" and i + 1 < length and script[i + 1] == "'":
                    buf.append(script[i + 1])
                    i += 2
                    continue
                if script[i] == "'":
                    i += 1
                    break
                i += 1
            continue
        if script[i] == "$":
            tag = _dollar_tag(script, i)
            if tag:
                end = script.find(tag, i + len(tag))
                stop = length if end < 0 else end + len(tag)
                buf.append(script[i:stop])
                i = stop
                continue
        if script[i] == ";":
            text = "".join(buf).strip()
            if text:
                statements.append(text)
            buf = []
            i += 1
            continue
        buf.append(script[i])
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def migrate(database_url: str) -> list[str]:
    """Aplica o que ainda não está em schema_migrations. Devolve as versões novas."""
    applied: list[str] = []
    with connect(database_url) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    for path in migration_files():
        version = path.stem
        with connect(database_url) as conn:
            done = conn.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,)).fetchone()
            if done:
                continue
            for statement in sql_statements(path.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        applied.append(version)
    return applied


def _dollar_tag(script: str, start: int) -> str | None:
    if start >= len(script) or script[start] != "$":
        return None
    end = start + 1
    while end < len(script) and (script[end].isalnum() or script[end] == "_"):
        end += 1
    if end < len(script) and script[end] == "$":
        return script[start : end + 1]
    return None
