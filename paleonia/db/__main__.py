"""Aplica as migrations e cria usuários no Postgres.

    python -m paleonia.db
    python -m paleonia.db add-user maria
"""
from __future__ import annotations

import argparse
import getpass
import sys

from paleonia.config import get_settings
from paleonia.db.connect import safe_message
from paleonia.db.migrate import migrate
from paleonia.db.users import add_user, seed_from_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrations e usuários do PaleonIA no Postgres.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("migrate", help="Aplica as migrations e, se a tabela estiver vazia, cria o usuário do .env")
    add = sub.add_parser("add-user", help="Cria um usuário pedindo a senha")
    add.add_argument("username")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_url:
        print("Defina DATABASE_URL no .env.", file=sys.stderr)
        return 1
    try:
        applied = migrate(settings.database_url)
    except Exception as exc:
        print(safe_message(exc), file=sys.stderr)
        return 1
    if applied:
        print("Migrations aplicadas: " + ", ".join(applied))
    else:
        print("Migrations já estão em dia.")

    if args.command == "add-user":
        password = getpass.getpass("Senha: ")
        confirm = getpass.getpass("Repita a senha: ")
        if password != confirm:
            print("As senhas não conferem.", file=sys.stderr)
            return 1
        try:
            add_user(settings.database_url, args.username, password)
        except Exception as exc:
            print(safe_message(exc), file=sys.stderr)
            return 1
        print(f"Usuário criado: {args.username.strip()}")
        return 0

    try:
        created = seed_from_settings(settings)
    except Exception as exc:
        print(safe_message(exc), file=sys.stderr)
        return 1
    if created:
        print(f"Usuário inicial criado: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
