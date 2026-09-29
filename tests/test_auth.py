import tempfile
import unittest

from fastapi.testclient import TestClient

from paleonia import config
from paleonia.auth import issue_token, read_username
from paleonia.desk import create_app


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.previous = config._SETTINGS
        base = config.get_settings()
        config._SETTINGS = config.replace(
            base,
            auth_username="paleonia",
            auth_password="segredo",
            auth_secret="chave-de-teste",
        )

    def tearDown(self):
        config._SETTINGS = self.previous

    def test_api_and_images_require_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TestClient(create_app(tmp)) as client:
                status = client.get("/api/auth")
                self.assertEqual(status.status_code, 200)
                self.assertTrue(status.json()["required"])
                self.assertFalse(status.json()["authenticated"])
                self.assertEqual(client.get("/api/session").status_code, 401)
                self.assertEqual(client.get("/images/p001").status_code, 401)
                denied = client.post("/api/login", json={"username": "paleonia", "password": "errada"})
                self.assertEqual(denied.status_code, 401)
                allowed = client.post("/api/login", json={"username": "paleonia", "password": "segredo"})
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(client.get("/api/session").status_code, 200)
                self.assertNotIn("segredo", allowed.text)
                client.post("/api/logout")
                self.assertEqual(client.get("/api/session").status_code, 401)

    def test_token_rejects_a_tampered_signature(self):
        settings = config.get_settings()
        token = issue_token(settings, "paleonia", now=1_000)
        self.assertEqual(read_username(token, settings, now=1_000), "paleonia")
        self.assertIsNone(read_username(token + "x", settings, now=1_000))
        self.assertIsNone(read_username(token, settings, now=1_000 + 60 * 60 * 24 * 8))
