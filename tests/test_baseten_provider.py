import io
import json
import os
import socket
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from agent.baseten import BasetenMuseProvider, DEFAULT_MODEL
from agent.providers import ProviderDecision, ProviderError, ProviderRequest
from agent.tools import MODEL_TOOLS
from diagnostic_core.contracts import MODEL_ACTION_FIELDS, TRUSTED_INGESTION_ACTION_FIELDS
from diagnostic_core.engine import DiagnosticSession


_TOOL_RESPONSE = {"choices": [{"message": {"tool_calls": [{"id": "call_1", "type": "function", "function": {
    "name": "propose_hypothesis", "arguments": json.dumps({"cause": "Cause A"}),
}}]}}]}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class BasetenMuseProviderTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network access forbidden in Baseten tests"))
            guard.start()
            self.addCleanup(guard.stop)

    def _request(self, session=None):
        snapshot = (session or DiagnosticSession("Laptop powers on but has no display")).snapshot
        return ProviderRequest(
            problem=snapshot.problem,
            session=snapshot,
            tools=MODEL_TOOLS,
            feedback=(),
            turn_count=snapshot.turn_count,
            completion_attempts=snapshot.completion_attempts,
            remaining_provider_steps=10,
        )

    def _decide(self, script, **provider_kwargs):
        payloads = []

        def fake_open(request, timeout=None):
            payloads.append(json.loads(request.data.decode("utf-8")))
            entry = script.pop(0)
            if isinstance(entry, BaseException):
                raise entry
            return _FakeResponse(entry)

        kwargs = {"api_key": "test-key"}
        kwargs.update(provider_kwargs)
        with patch("urllib.request.urlopen", side_effect=fake_open):
            decision = BasetenMuseProvider(**kwargs).decide(self._request())
        return decision, payloads
    def test_tool_call_is_converted_to_provider_decision(self):
        session = DiagnosticSession("Laptop powers on but has no display").snapshot
        request = ProviderRequest(
            problem=session.problem,
            session=session,
            tools=(
                {
                    "name": "propose_hypothesis",
                    "description": "Propose a cause",
                    "parameters": {
                        "type": "object",
                        "properties": {"cause": {"type": "string"}},
                        "required": ["cause"],
                        "additionalProperties": False,
                    },
                },
            ),
            feedback=(),
            turn_count=0,
            completion_attempts=0,
            remaining_provider_steps=10,
        )
        response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "propose_hypothesis",
                                    "arguments": json.dumps({"cause": "Memory not seated"}),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        with patch("urllib.request.urlopen", return_value=_FakeResponse(response)) as mocked:
            provider = BasetenMuseProvider(api_key="test-key")
            decision = provider.decide(request)

        self.assertEqual(len(decision.calls), 1)
        self.assertEqual(decision.calls[0].name, "propose_hypothesis")
        self.assertEqual(decision.calls[0].arguments["cause"], "Memory not seated")

        sent = json.loads(mocked.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["model"], DEFAULT_MODEL)
        self.assertEqual(sent["tool_choice"], "required")
        self.assertFalse(sent["parallel_tool_calls"])

    def test_missing_key_fails_clearly(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProviderError, "BASETEN_API_KEY"):
                BasetenMuseProvider()

    def test_tool_schema_names_match_model_actions(self):
        _, payloads = self._decide([_TOOL_RESPONSE])
        self.assertEqual(
            {tool["function"]["name"] for tool in payloads[0]["tools"]},
            set(MODEL_ACTION_FIELDS),
        )

    def test_trusted_ingestion_absent_from_outbound_tools(self):
        _, payloads = self._decide([_TOOL_RESPONSE])
        names = {tool["function"]["name"] for tool in payloads[0]["tools"]}
        for action in TRUSTED_INGESTION_ACTION_FIELDS:
            with self.subTest(action=action):
                self.assertNotIn(action, names)

    def test_image_included_when_provided(self):
        _, payloads = self._decide([_TOOL_RESPONSE], image_data_url="data:image/png;base64,AAA")
        content = payloads[0]["messages"][1]["content"]
        images = [block for block in content if block.get("type") == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image_url"]["url"], "data:image/png;base64,AAA")

    def test_set_image_updates_later_decisions(self):
        seen = []

        def fake_open(request, timeout=None):
            seen.append(json.loads(request.data.decode("utf-8")))
            return _FakeResponse(_TOOL_RESPONSE)

        provider = BasetenMuseProvider(api_key="test-key")
        with patch("urllib.request.urlopen", side_effect=fake_open):
            provider.decide(self._request())
            provider.set_image("data:image/png;base64,BBB")
            provider.decide(self._request())
        first = seen[0]["messages"][1]["content"]
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["type"], "text")
        updated = seen[1]["messages"][1]["content"]
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[1]["image_url"]["url"], "data:image/png;base64,BBB")

    def test_empty_tool_calls_returns_empty_decision(self):
        decision, _ = self._decide([{"choices": [{"message": {"content": "hi"}}]}])
        self.assertEqual(decision, ProviderDecision(()))

    def test_finish_length_rejected(self):
        with self.assertRaisesRegex(ProviderError, "truncated"):
            self._decide([{"choices": [{"finish_reason": "length", "message": {}}]}])

    def test_malformed_arguments_json_rejected(self):
        bad = {"choices": [{"message": {"tool_calls": [{"id": "1", "type": "function", "function": {
            "name": "propose_hypothesis", "arguments": "nope{",
        }}]}}]}
        with self.assertRaisesRegex(ProviderError, "unusable"):
            self._decide([bad])

    def test_malformed_response_shape_rejected(self):
        for payload in ({"choices": []}, {"nope": True}):
            with self.subTest(payload=payload), self.assertRaises(ProviderError):
                self._decide([payload])

    def test_http_error_surfaces_status(self):
        error = HTTPError("http://x", 500, "Server Error", {}, io.BytesIO(b"broken"))
        with self.assertRaisesRegex(ProviderError, "500"):
            self._decide([error])

    def test_network_error_safe(self):
        with self.assertRaisesRegex(ProviderError, "connection error"):
            self._decide([URLError("refused")])


if __name__ == "__main__":
    unittest.main()
