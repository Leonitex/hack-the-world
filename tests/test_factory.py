"""Provider factory tests. No network; SDK boundary faked where needed."""

import json
import os
import socket
import unittest
from unittest.mock import patch

from agent.baseten import BasetenMuseProvider
from agent.factory import create_provider
from agent.loop import AgentLoop, LoopOutcome
from agent.meta_provider import MetaProvider
from agent.providers import FakeProvider, ProviderError, ProviderRequest
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


    def test_e2e_fixture_selected_without_keys(self):
        with patch.dict(os.environ, {"HTW_E2E_FAKE_PROVIDER": "1"}, clear=True):
            provider, label = create_provider()
        self.assertIsInstance(provider, FakeProvider)
        self.assertIn("E2E fixture", label)

    def test_e2e_fixture_requires_exact_opt_in(self):
        for value in ("0", "yes", "true", ""):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"HTW_E2E_FAKE_PROVIDER": value}, clear=True):
                    with self.assertRaisesRegex(ProviderError, "No provider key"):
                        create_provider()

    def test_e2e_fixture_drives_two_distinct_turns(self):
        with patch.dict(os.environ, {"HTW_E2E_FAKE_PROVIDER": "1"}, clear=True):
            provider, _ = create_provider()
        core = DiagnosticSession("E2E problem")
        core.execute("record_evidence", {"source": "user_text", "statement": "E2E problem",
                                         "provenance": {"reporter": "e2e"}})
        loop = AgentLoop(core, provider, max_provider_steps=14, max_advance_steps=14)
        first = loop.run()
        self.assertEqual(first.outcome, LoopOutcome.NEEDS_INPUT)
        first_action = first.session.next_action.action
        self.assertIn("E2E check one", first_action)
        loop.resume_with_result("E2E result one", {"reporter": "e2e"})
        second = loop.run()
        self.assertEqual(second.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertIn("E2E check two", second.session.next_action.action)
        self.assertNotEqual(second.session.next_action.action, first_action)

    def test_e2e_repeat_marker_selects_repeat_guard_script(self):
        with patch.dict(os.environ, {"HTW_E2E_FAKE_PROVIDER": "1"}, clear=True):
            provider, _ = create_provider()
        core = DiagnosticSession("E2E e2e-repeat device is silent")
        core.execute("record_evidence", {"source": "user_text", "statement": "E2E problem",
                                         "provenance": {"reporter": "e2e"}})
        loop = AgentLoop(core, provider, max_provider_steps=14, max_advance_steps=14)
        first = loop.run()
        self.assertEqual(first.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertIn("E2E repeat check", first.session.next_action.action)
        loop.resume_with_result("E2E repeat result", {"reporter": "e2e"})
        second = loop.run()
        self.assertEqual(second.outcome, LoopOutcome.NEEDS_INPUT)
        # The verbatim repeat is blocked; the distinct follow-up is asked.
        self.assertIn("E2E distinct follow-up", second.session.next_action.action)


if __name__ == "__main__":
    unittest.main()
