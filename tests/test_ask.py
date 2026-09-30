import io
import json
import os
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

import numpy as np

from paleonia.reading.ask import ask
from paleonia.config import Settings, _llm_choice


def _api_settings(**overrides) -> Settings:
    values = dict(
        llm_provider="openai",
        llm_model="qwen/qwen3-vl-8b-instruct",
        llm_base_url="https://openrouter.ai/api/v1",
        llm_api_key="sk-test-secret",
        llm_attempts=1,
        llm_json_mode=True,
        app_name="PaleonIA",
    )
    values.update(overrides)
    return Settings(**values)


def _response(payload: dict):
    class _Body:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    return _Body()


class RemoteReaderTests(unittest.TestCase):
    def test_openrouter_alias_uses_openai_protocol_and_qwen_slug(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openrouter"}, clear=False):
            os.environ.pop("LLM_BASE_URL", None)
            os.environ.pop("LLM_MODEL", None)
            provider, model, base = _llm_choice()
        self.assertEqual(provider, "openai")
        self.assertEqual(model, "qwen/qwen3-vl-8b-instruct")
        self.assertEqual(base, "https://openrouter.ai/api/v1")

    def test_openai_compatible_post_sends_image_and_hides_the_key(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return _response({"choices": [{"message": {"content": '{"linhas":["abc"]}'}}]})

        image = np.zeros((8, 12, 3), np.uint8)
        with patch("paleonia.reading.ask.urllib.request.urlopen", fake_urlopen):
            result = ask(_api_settings(llm_timeout=12), "leia", image, attempts=1)

        self.assertEqual(result, {"linhas": ["abc"]})
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(captured["auth"], "Bearer sk-test-secret")
        self.assertEqual(captured["body"]["model"], "qwen/qwen3-vl-8b-instruct")
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
        image_url = captured["body"]["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertNotIn("sk-test-secret", json.dumps(captured["body"]))

    def test_drops_json_mode_when_the_api_rejects_it(self):
        calls = []

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode())
            calls.append(body)
            if "response_format" in body:
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "bad",
                    Message(),
                    io.BytesIO(b'{"error":"response_format is unsupported"}'),
                )
            return _response({"choices": [{"message": {"content": [{"type": "text", "text": '{"linhas":["ok"]}'}]}}]})

        with patch("paleonia.reading.ask.urllib.request.urlopen", fake_urlopen):
            result = ask(_api_settings(), "leia", np.zeros((4, 4, 3), np.uint8), attempts=1)

        self.assertEqual(result["linhas"], ["ok"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("response_format", calls[1])

    def test_missing_api_key_fails_before_the_request(self):
        def fail_urlopen(*_args, **_kwargs):
            raise AssertionError("não deveria chamar a API")

        with patch("paleonia.reading.ask.urllib.request.urlopen", fail_urlopen):
            with self.assertRaises(ValueError) as caught:
                ask(_api_settings(llm_api_key=""), "leia", np.zeros((4, 4, 3), np.uint8), attempts=1)
        self.assertIn("LLM_API_KEY", str(caught.exception))
