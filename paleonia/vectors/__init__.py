"""Gravação e busca vetorial das transcrições no Postgres."""

from paleonia.vectors.index import VectorIndex, persist_page, schedule_remove

__all__ = ["VectorIndex", "persist_page", "schedule_remove"]
