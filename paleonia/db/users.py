"""Usuários do PaleonIA gravados no Postgres."""
from __future__ import annotations

from paleonia.config import Settings
from paleonia.db.connect import connect
from paleonia.db.migrate import migrate
from paleonia.db.passwords import hash_password, verify_password


class UserDirectory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active = False
        self.error = ""
        self.applied: list[str] = []

    def prepare(self) -> list[str]:
        if not self.settings.database_url:
            return []
        try:
            self.applied = migrate(self.settings.database_url)
            created = seed_from_settings(self.settings)
            self.active = user_count(self.settings.database_url) > 0
            self.error = ""
            if created:
                print(f"Usuário inicial criado no Postgres: {created}")
            if self.applied:
                print("Migrations aplicadas: " + ", ".join(self.applied))
        except Exception as exc:
            from paleonia.db.connect import safe_message

            self.active = False
            self.error = safe_message(exc)
            print(f"Postgres: {self.error}")
        return self.applied

    def authenticate(self, username: str, password: str) -> str | None:
        row = _find(self.settings.database_url, username)
        if row is None or not verify_password(password, row[2]):
            return None
        return str(row[1])

    def id_of(self, username: str) -> int | None:
        row = _find(self.settings.database_url, username)
        if row is None:
            return None
        return int(row[0])


def seed_from_settings(settings: Settings) -> str | None:
    username = settings.auth_username.strip()
    password = settings.auth_password
    if not settings.database_url or not username or not password:
        return None
    if user_count(settings.database_url):
        return None
    add_user(settings.database_url, username, password)
    return username


def add_user(database_url: str, username: str, password: str) -> None:
    name = username.strip()
    if not name or not password:
        raise ValueError("Informe usuário e senha.")
    import psycopg

    try:
        with connect(database_url) as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (name, hash_password(password)),
            )
    except psycopg.errors.UniqueViolation as exc:
        raise ValueError("Esse usuário já existe.") from exc


def user_count(database_url: str) -> int:
    with connect(database_url) as conn:
        row = conn.execute("SELECT count(*) FROM users").fetchone()
    return int(row[0] if row else 0)


def _find(database_url: str, username: str):
    with connect(database_url) as conn:
        return conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,),
        ).fetchone()
