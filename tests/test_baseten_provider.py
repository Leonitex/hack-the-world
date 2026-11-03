import json
import unittest
from unittest.mock import patch

from agent.baseten import BasetenMuseProvider, DEFAULT_MODEL
from agent.providers import ProviderRequest
from diagnostic_core.engine import DiagnosticSession


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


if __name__ == "__main__":
    unittest.main()
