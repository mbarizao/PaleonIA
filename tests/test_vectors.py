import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from paleonia import config
from paleonia.api.app import create_app
from paleonia.vectors.embed import embed_texts, parse_ollama_embeddings, parse_openai_embeddings, vector_literal
from paleonia.vectors.index import VectorIndex, _safe_message
from paleonia.vectors.passages import Passage, passages_from_page, split_passages


def _page():
    return {
        "id": "p001",
        "filename": "folha.jpg",
        "lines": [
            {
                "id": "ln1",
                "box": [0, 0, 10, 10],
                "include": True,
                "parts": [{"id": "pt1", "text": "na igreja matriz"}],
            },
            {
                "id": "ln2",
                "box": [0, 20, 10, 30],
                "include": False,
                "parts": [{"id": "pt2", "text": "   "}],
            },
        ],
    }


class PassageTests(unittest.TestCase):
    def test_keeps_written_text_and_skips_blank_parts(self):
        passages = passages_from_page(_page())
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0].part_id, "pt1")
        self.assertEqual(passages[0].linha_documento, 1)
        self.assertEqual(passages[0].linha_transcrita, 1)
        self.assertEqual(passages[0].text, "na igreja matriz")
        self.assertFalse(passages[0].confirmed)

    def test_confirmed_part_stays_marked(self):
        page = _page()
        page["lines"][0]["parts"][0]["confirmed"] = True
        passages = passages_from_page(page)
        self.assertTrue(passages[0].confirmed)

    def test_unchanged_text_is_not_embedded_again(self):
        passage = Passage("pt1", "p001", "folha.jpg", "ln1", 1, 1, "na igreja matriz")
        same = Passage("pt1", "p001", "folha.jpg", "ln1", 2, 1, "na igreja matriz")
        fresh = Passage("pt3", "p001", "folha.jpg", "ln3", 3, 2, "o adro")
        to_embed, to_refresh, to_delete = split_passages([same, fresh], {"pt1": passage.content_hash, "pt-old": "x"})
        self.assertEqual([item.part_id for item in to_embed], ["pt3"])
        self.assertEqual([item.part_id for item in to_refresh], ["pt1"])
        self.assertEqual(to_delete, ["pt-old"])

    def test_index_stays_quiet_without_database_url(self):
        index = VectorIndex(config.replace(config.get_settings(), database_url=""))
        self.assertFalse(index.enabled)
        self.assertEqual(index.save_page(_page()), None)

    def test_database_errors_hide_the_url(self):
        message = _safe_message(RuntimeError("connection to postgresql://paleonia:segredo@db/paleonia failed"))
        self.assertNotIn("segredo", message)
        self.assertNotIn("postgresql://", message)


class EmbedTests(unittest.TestCase):
    def test_ollama_and_openai_payloads_keep_order(self):
        ollama = parse_ollama_embeddings({"embeddings": [[0.1, 0.2], [0.3, 0.4]]}, 2)
        self.assertEqual(ollama[1][0], 0.3)
        openai = parse_openai_embeddings(
            {"data": [{"index": 1, "embedding": [0.4]}, {"index": 0, "embedding": [0.2]}]},
            2,
        )
        self.assertEqual(openai[0], [0.2])
        self.assertTrue(vector_literal([0.5, 1]).startswith("["))

    def test_rejects_a_vector_with_the_wrong_size(self):
        settings = config.replace(
            config.get_settings(),
            embed_provider="ollama",
            embed_model="nomic-embed-text",
            embed_dimensions=2,
            embed_timeout=5,
            ollama_host="http://127.0.0.1:11434",
        )

        def fake_urlopen(request, timeout):
            self.assertIn("/api/embed", request.full_url)
            body = json.loads(request.data.decode())
            self.assertEqual(body["input"], ["igreja"])
            self.assertEqual(timeout, 5)
            return _response({"embeddings": [[0.1, 0.2, 0.3]]})

        with patch("paleonia.vectors.embed.urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(RuntimeError) as caught:
                embed_texts(["igreja"], settings)
        self.assertIn("EMBED_DIMENSIONS", str(caught.exception))


class SearchApiTests(unittest.TestCase):
    def test_search_without_database_explains_how_to_enable_it(self):
        previous = config._SETTINGS
        config._SETTINGS = config.replace(config.get_settings(), database_url="")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with TestClient(create_app(tmp)) as client:
                    _login_if_needed(client)
                    missing = client.get("/api/search")
                    self.assertEqual(missing.status_code, 400)
                    found = client.get("/api/search", params={"q": "igreja"})
                    session = client.get("/api/session")
        finally:
            config._SETTINGS = previous
        self.assertEqual(found.status_code, 200, found.text)
        body = found.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["results"], [])
        self.assertIn("DATABASE_URL", body["detail"])
        self.assertFalse(session.json()["vector_search"])

    def test_search_returns_indexed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(tmp)

            class Stub:
                enabled = True

                def search(self, query, limit=8, user_id=None):
                    self.query = query
                    self.limit = limit
                    self.user_id = user_id
                    return [
                        {
                            "page_id": "p001",
                            "filename": "folha.jpg",
                            "line_id": "ln1",
                            "part_id": "pt1",
                            "linha_documento": 4,
                            "linha_transcrita": 2,
                            "text": "na igreja matriz",
                            "score": 0.91,
                        }
                    ]

            stub = Stub()
            app.state.vectors = stub
            with TestClient(app) as client:
                _login_if_needed(client)
                response = client.get("/api/search", params={"q": "templo", "limit": 3})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(stub.query, "templo")
        self.assertEqual(stub.limit, 3)
        self.assertEqual(response.json()["results"][0]["text"], "na igreja matriz")


def _login_if_needed(client: TestClient) -> None:
    settings = config.get_settings()
    if not settings.auth_password:
        return
    response = client.post(
        "/api/login",
        json={"username": settings.auth_username, "password": settings.auth_password},
    )
    if response.status_code != 200:
        raise AssertionError(response.text)


def _response(payload: dict):
    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    return _Body()
