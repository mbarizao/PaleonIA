import unittest

from paleonia.db.migrate import EMBEDDING_DIMENSIONS, migration_files, sql_statements
from paleonia.db.passwords import hash_password, verify_password


class PasswordTests(unittest.TestCase):
    def test_hash_checks_the_same_password_and_rejects_another(self):
        stored = hash_password("segredo")
        self.assertTrue(verify_password("segredo", stored))
        self.assertFalse(verify_password("outra", stored))
        self.assertNotIn("segredo", stored)
        self.assertFalse(verify_password("segredo", "texto-invalido"))


class MigrationTests(unittest.TestCase):
    def test_files_are_ordered_and_the_vector_column_matches_the_constant(self):
        names = [path.name for path in migration_files()]
        self.assertEqual(
            names,
            [
                "001_users.sql",
                "002_transcriptions.sql",
                "003_import_line_embeddings.sql",
                "004_transcription_confirmed.sql",
            ],
        )
        confirmed = migration_files()[3].read_text(encoding="utf-8")
        self.assertEqual(len(sql_statements(confirmed)), 1)
        self.assertIn("confirmed", confirmed)
        transcriptions = migration_files()[1].read_text(encoding="utf-8")
        self.assertIn(f"vector({EMBEDDING_DIMENSIONS})", transcriptions)
        self.assertEqual(len(sql_statements(transcriptions)), 5)
        legacy = migration_files()[2].read_text(encoding="utf-8")
        statements = sql_statements(legacy)
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("DO $$"))
        self.assertIn("line_embeddings", statements[0])
