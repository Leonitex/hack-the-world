"""Provider factory tests. No network; SDK boundary faked where needed."""

import json
import os
import socket
import unittest
from unittest.mock import patch

from agent.baseten import BasetenMuseProvider
from agent.factory import create_provider
from agent.meta_provider import MetaProvider
from agent.providers import ProviderError, ProviderRequest
from diagnostic_core.engine import DiagnosticSession


class FactoryTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network access forbidden in factory tests"))
            guard.start()
            self.addCleanup(guard.stop)

    def _recording_factory(self, built):
        class RecordingFactory:
            def __init__(self, **kwargs):
                built.append(kwargs)
                self.chat = None

        return RecordingFactory

    def test_explicit_baseten(self):
        with patch.dict(os.environ, {"BASETEN_API_KEY": "key", "HTW_PROVIDER": "baseten"}, clear=True):
            provider, label = create_provider()
        self.assertIsInstance(provider, BasetenMuseProvider)
        self.assertIn("Baseten", label)

    def test_explicit_meta(self):
        built = []
        with patch.dict(os.environ, {"MODEL_API_KEY": "key", "HTW_PROVIDER": "meta"}, clear=True):
            with patch("agent.meta_provider.OpenAI", self._recording_factory(built)):
                provider, label = create_provider()
        self.assertIsInstance(provider, MetaProvider)
        self.assertIn("muse-spark-1.3", label)
        self.assertEqual(built[0]["api_key"], "key")

    def test_explicit_meta_missing_key(self):
        with patch.dict(os.environ, {"HTW_PROVIDER": "meta"}, clear=True):
            with patch("agent.meta_provider.OpenAI", self._recording_factory([])):
                with self.assertRaisesRegex(ProviderError, "MODEL_API_KEY"):
                    create_provider()

    def test_auto_prefers_baseten(self):
        env = {"BASETEN_API_KEY": "b", "MODEL_API_KEY": "m", "HTW_PROVIDER": "auto"}
        with patch.dict(os.environ, env, clear=True):
            provider, label = create_provider()
        self.assertIsInstance(provider, BasetenMuseProvider)
        self.assertIn("Baseten", label)

    def test_auto_falls_back_to_meta(self):
        built = []
        with patch.dict(os.environ, {"MODEL_API_KEY": "m"}, clear=True):
            with patch("agent.meta_provider.OpenAI", self._recording_factory(built)):
                provider, label = create_provider()
        self.assertIsInstance(provider, MetaProvider)
        self.assertIn("Meta Model API", label)

    def test_auto_no_keys_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProviderError, "BASETEN_API_KEY.*MODEL_API_KEY"):
                create_provider()

    def test_unknown_choice_errors(self):
        with patch.dict(os.environ, {"HTW_PROVIDER": "nope"}, clear=True):
            with self.assertRaisesRegex(ProviderError, "Unknown HTW_PROVIDER"):
                create_provider()

    def test_image_passed_through_to_baseten(self):
        seen = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {}}]}).encode("utf-8")

        def fake_open(request, timeout=None):
            seen.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        with patch.dict(os.environ, {"BASETEN_API_KEY": "key"}, clear=True):
            provider, _ = create_provider("data:image/png;base64,AAA")
            snapshot = DiagnosticSession("Laptop powers on but has no display").snapshot
            request = ProviderRequest(
                problem=snapshot.problem, session=snapshot, tools=(),
                feedback=(), turn_count=0, completion_attempts=0,
                remaining_provider_steps=1,
            )
            with patch("urllib.request.urlopen", side_effect=fake_open):
                provider.decide(request)
        content = seen[0]["messages"][1]["content"]
        images = [block for block in content if block.get("type") == "image_url"]
        self.assertEqual([image["image_url"]["url"] for image in images], ["data:image/png;base64,AAA"])


if __name__ == "__main__":
    unittest.main()
