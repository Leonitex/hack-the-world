"""Meta provider adapter tests. The SDK boundary is faked; no network, no key."""

import json
import os
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent import (
    AgentLoop, LoopOutcome, MODEL_TOOLS, MetaProvider, ProviderDecision,
    ProviderError, ProviderRequest, StepFeedback, ToolCall,
)
from agent import meta_provider as adapter
from diagnostic_core import DiagnosticSession
from diagnostic_core.contracts import MODEL_ACTION_FIELDS, TRUSTED_INGESTION_ACTION_FIELDS
from diagnostic_core.models import SessionStatus as S


PROBLEM = "Unit under test fails its power-on check."


class _FakeSDKError:
    """Bypass real SDK __init__ signatures (e.g. required response/body).

    Instances are still caught by the adapter's except clauses through the
    SDK base class; status_code/body are set as plain attributes instead.
    Works whether the openai package is installed or not.
    """

    def __init__(self, message="fake SDK error", **attrs):
        Exception.__init__(self, message)
        for key, value in attrs.items():
            setattr(self, key, value)


class FakeAuthError(_FakeSDKError, adapter.AuthenticationError):
    pass


class FakeRateLimitError(_FakeSDKError, adapter.RateLimitError):
    pass


class FakeTimeoutError(_FakeSDKError, adapter.APITimeoutError):
    pass


class FakeConnectionError(_FakeSDKError, adapter.APIConnectionError):
    pass


class FakeServerError(_FakeSDKError, adapter.APIStatusError):
    status_code = 503


class FakeNotFoundError(_FakeSDKError, adapter.NotFoundError):
    pass


class FakeBadRequestError(_FakeSDKError, adapter.BadRequestError):
    pass


class FakeSDKError(_FakeSDKError, adapter.OpenAIError):
    pass


class FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("FakeCompletions script exhausted")
        entry = self._script.pop(0)
        if isinstance(entry, BaseException):
            raise entry
        if callable(entry):
            return entry(kwargs)
        return entry


class FakeClient:
    def __init__(self, script):
        self.completions = FakeCompletions(script)
        self.chat = SimpleNamespace(completions=self.completions)


def tool_response(*calls):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(id=f"call_{index}", function=SimpleNamespace(
                name=name, arguments=raw if isinstance(raw, str) else json.dumps(raw)))
            for index, (name, raw) in enumerate(calls)
        ],
    ))])


def text_response(content="Plain text with no tool call."):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=None))])


def update_args(hypothesis_id, supporting=()):
    return {
        "hypothesis_id": hypothesis_id, "status": "supported",
        "supporting": list(supporting), "contradicting": [],
        "resolutions": {}, "rationale": "Assessment follows the recorded observations.",
    }


class MetaProviderTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network access forbidden in Meta tests"))
            guard.start()
            self.addCleanup(guard.stop)
        self.core = DiagnosticSession(PROBLEM)

    def request_for(self, core=None, feedback=()):
        core = core or self.core
        snapshot = core.snapshot
        return ProviderRequest(
            problem=snapshot.problem, session=snapshot, tools=MODEL_TOOLS,
            feedback=tuple(feedback), turn_count=snapshot.turn_count,
            completion_attempts=snapshot.completion_attempts,
            remaining_provider_steps=10,
        )

    def seed(self, statement="Initial observation", core=None):
        return (core or self.core).execute("record_evidence", {
            "source": "user_text", "statement": statement, "provenance": {"reporter": "user"},
        }).record_id

    def test_converts_model_tools_to_openai_function_format(self):
        client = FakeClient([text_response()])
        provider = MetaProvider(client=client)
        decision = provider.decide(self.request_for())
        self.assertEqual(decision, ProviderDecision(()))
        sent = client.completions.calls[0]
        self.assertEqual(sent["model"], "muse-spark-1.3")
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertFalse(sent["parallel_tool_calls"])
        self.assertEqual([message["role"] for message in sent["messages"]], ["developer", "user"])
        self.assertEqual(len(sent["tools"]), len(MODEL_TOOLS))
        for expected, actual in zip(MODEL_TOOLS, sent["tools"]):
            with self.subTest(tool=expected["name"]):
                self.assertEqual(actual, {
                    "type": "function",
                    "function": {
                        "name": expected["name"],
                        "description": expected["description"],
                        "parameters": expected["parameters"],
                    },
                })
                self.assertRegex(actual["function"]["name"], r"^[A-Za-z0-9_.-]+$")
                self.assertLessEqual(actual["function"]["name"].count("."), 1)
        self.assertEqual(
            {tool["function"]["name"] for tool in sent["tools"]}, set(MODEL_ACTION_FIELDS),
        )

    def test_trusted_ingestion_absent_from_outbound_tools(self):
        client = FakeClient([text_response()])
        MetaProvider(client=client).decide(self.request_for())
        names = {tool["function"]["name"] for tool in client.completions.calls[0]["tools"]}
        for action in TRUSTED_INGESTION_ACTION_FIELDS:
            with self.subTest(action=action):
                self.assertNotIn(action, names)

    def test_model_and_base_url_app_controlled(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = MetaProvider(client=FakeClient([]))
            self.assertEqual(provider.model, "muse-spark-1.3")
            self.assertEqual(provider.base_url, "https://api.meta.ai/v1")
        explicit = MetaProvider(
            client=FakeClient([]), model="custom-model", base_url="https://example.invalid/v1",
        )
        self.assertEqual(explicit.model, "custom-model")
        self.assertEqual(explicit.base_url, "https://example.invalid/v1")
        with patch.dict(os.environ, {"META_MODEL_ID": "env-model", "META_BASE_URL": "https://env.invalid/v1"}):
            from_env = MetaProvider(client=FakeClient([]))
            self.assertEqual(from_env.model, "env-model")
            self.assertEqual(from_env.base_url, "https://env.invalid/v1")
            explicit_wins = MetaProvider(client=FakeClient([]), model="explicit-model")
            self.assertEqual(explicit_wins.model, "explicit-model")
        client = FakeClient([text_response()])
        MetaProvider(client=client, model="custom-model").decide(self.request_for())
        self.assertEqual(client.completions.calls[0]["model"], "custom-model")

    def test_api_key_from_env_and_never_embedded(self):
        built = []

        class RecordingFactory:
            def __init__(self, **kwargs):
                built.append(kwargs)
                self.chat = SimpleNamespace(completions=FakeCompletions([text_response()]))

        key = "MODEL_API_KEY-fake-secret-value"
        with patch.dict(os.environ, {"MODEL_API_KEY": key}, clear=True):
            with patch.object(adapter, "OpenAI", RecordingFactory):
                MetaProvider().decide(self.request_for())
        self.assertEqual(built[0]["api_key"], key)
        self.assertEqual(built[0]["base_url"], "https://api.meta.ai/v1")
        self.assertNotIn("timeout", built[0])
        with patch.dict(os.environ, {"MODEL_API_KEY": "env-key"}, clear=True):
            with patch.object(adapter, "OpenAI", RecordingFactory):
                MetaProvider(api_key="explicit-key")
                MetaProvider(timeout=12.5)
        self.assertEqual(built[1]["api_key"], "explicit-key")
        self.assertEqual(built[2]["timeout"], 12.5)
        with patch.dict(os.environ, {"META_MODEL_API_KEY": "fallback-key"}, clear=True):
            with patch.object(adapter, "OpenAI", RecordingFactory):
                MetaProvider()
        self.assertEqual(built[3]["api_key"], "fallback-key")

    def test_api_key_absent_from_rendered_payload(self):
        key = "MODEL_API_KEY-fake-secret-value"
        client = FakeClient([text_response()])
        with patch.dict(os.environ, {"MODEL_API_KEY": key}, clear=True):
            MetaProvider(client=client).decide(self.request_for())
        payload = json.dumps(client.completions.calls[0])
        self.assertNotIn(key, payload)
        self.assertNotIn("MODEL_API_KEY", payload)

    def test_missing_key_fails_before_network(self):
        built = []

        class RecordingFactory:
            def __init__(self, **kwargs):
                built.append(kwargs)

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(adapter, "OpenAI", RecordingFactory):
                with self.assertRaisesRegex(ProviderError, "MODEL_API_KEY"):
                    MetaProvider()
        self.assertEqual(built, [])

    def test_missing_sdk_fails_clearly(self):
        with patch.object(adapter, "OpenAI", None):
            with self.assertRaisesRegex(ProviderError, "openai package"):
                MetaProvider()

    def test_tool_call_response_becomes_toolcall(self):
        args = {
            "hypothesis_id": "h1", "status": "supported",
            "supporting": ["e1", "e2"], "contradicting": [],
            "resolutions": {"e3": "e1"}, "rationale": "Unicode check passed.",
        }
        provider = MetaProvider(client=FakeClient([tool_response(("update_hypothesis", args))]))
        decision = provider.decide(self.request_for())
        self.assertEqual(decision, ProviderDecision((ToolCall("update_hypothesis", args),)))

    def test_malformed_json_arguments_fail_safely(self):
        for raw in ("not json{", "[1, 2]", '"bare"', "null", ""):
            with self.subTest(raw=raw):
                provider = MetaProvider(
                    client=FakeClient([tool_response(("propose_hypothesis", raw))]),
                )
                with self.assertRaises(ProviderError):
                    provider.decide(self.request_for())
        self.assertEqual(self.core.snapshot.turn_count, 0)
        self.assertEqual(self.core.snapshot.evidence, ())

    def test_malformed_response_shapes_fail_safely(self):
        empty_choices = SimpleNamespace(choices=[])
        no_message = SimpleNamespace(choices=[SimpleNamespace(message=None)])
        no_function = tool_response(("propose_hypothesis", {"cause": "Cause A"}))
        no_function.choices[0].message.tool_calls[0].function = None
        for response in (empty_choices, no_message, no_function):
            with self.subTest(response=response):
                provider = MetaProvider(client=FakeClient([response]))
                with self.assertRaisesRegex(ProviderError, "Malformed Meta response"):
                    provider.decide(self.request_for())
        self.assertEqual(self.core.snapshot.turn_count, 0)

    def test_zero_calls_safe(self):
        for response in (text_response(), tool_response()):
            with self.subTest(response=response):
                core = DiagnosticSession(PROBLEM)
                provider = MetaProvider(client=FakeClient([response]))
                self.assertEqual(
                    provider.decide(self.request_for(core)), ProviderDecision(()),
                )
        core = DiagnosticSession(PROBLEM)
        provider = MetaProvider(client=FakeClient([text_response()]))
        result = AgentLoop(core, provider, max_provider_steps=1).run()
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(core.snapshot.turn_count, 0)

    def test_multiple_calls_safe_none_execute(self):
        provider = MetaProvider(client=FakeClient([tool_response(
            ("propose_hypothesis", {"cause": "Cause A"}),
            ("propose_hypothesis", {"cause": "Cause B"}),
        )]))
        decision = provider.decide(self.request_for())
        self.assertEqual(len(decision.calls), 2)
        core = DiagnosticSession(PROBLEM)
        provider = MetaProvider(client=FakeClient([tool_response(
            ("propose_hypothesis", {"cause": "Cause A"}),
            ("propose_hypothesis", {"cause": "Cause B"}),
        )]))
        result = AgentLoop(core, provider, max_provider_steps=1).run()
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(core.snapshot.turn_count, 0)
        self.assertEqual(core.snapshot.hypotheses, ())

    def test_auth_failure_maps(self):
        provider = MetaProvider(
            client=FakeClient([FakeAuthError("401 Unauthorized")] * 2),
        )
        with self.assertRaisesRegex(ProviderError, "authentication"):
            provider.decide(self.request_for())
        try:
            provider.decide(self.request_for())
        except ProviderError as exc:
            self.assertIn("MODEL_API_KEY", str(exc))
        self.assertEqual(self.core.snapshot.turn_count, 0)

    def test_api_failures_map_without_mutation(self):
        cases = [
            (FakeRateLimitError("429"), "rate limit"),
            (FakeTimeoutError("timed out"), "timed out"),
            (FakeConnectionError("reset"), "network"),
            (FakeServerError("bad gateway"), "server failure"),
            (FakeNotFoundError("no such model"), "muse-spark-1.3"),
            (FakeBadRequestError("bad tools"), "rejected"),
            (FakeSDKError("odd"), "Meta API failure"),
        ]
        for error, keyword in cases:
            with self.subTest(error=error):
                provider = MetaProvider(client=FakeClient([error]))
                with self.assertRaisesRegex(ProviderError, keyword):
                    provider.decide(self.request_for())
        provider = MetaProvider(client=FakeClient([FakeServerError("bad gateway")]))
        with self.assertRaisesRegex(ProviderError, "503"):
            provider.decide(self.request_for())
        self.assertEqual(self.core.snapshot.turn_count, 0)
        self.assertEqual(self.core.snapshot.evidence, ())
        core = DiagnosticSession(PROBLEM)
        provider = MetaProvider(client=FakeClient(
            [tool_response(("propose_hypothesis", {"cause": "Cause A"}))]
            + [FakeRateLimitError("429")] * 3,
        ))
        result = AgentLoop(core, provider, max_provider_steps=4).run()
        self.assertEqual(result.outcome, LoopOutcome.PROVIDER_ERROR)
        self.assertEqual(core.snapshot.turn_count, 1)
        self.assertEqual(core.snapshot.status, S.INVESTIGATING)

    def test_meta_drives_loop_to_needs_input(self):
        client = FakeClient([
            tool_response(("propose_hypothesis", {"cause": "Cause A"})),
            tool_response(("propose_hypothesis", {"cause": "Cause B"})),
            tool_response(("request_user_evidence", {
                "action": "Perform the next check and report the outcome.",
                "observations": ["What changed?", "What was observed?"],
            })),
        ])
        result = AgentLoop(self.core, MetaProvider(client=client)).run()
        self.assertEqual(result.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(len(self.core.snapshot.hypotheses), 2)
        self.assertEqual(len(client.completions.calls), 3)
        for call in client.completions.calls:
            self.assertEqual(len(call["tools"]), len(MODEL_TOOLS))

    def test_resume_then_verified_recommendation(self):
        first = FakeClient([
            tool_response(("propose_hypothesis", {"cause": "Cause A"})),
            tool_response(("request_user_evidence", {
                "action": "Perform the next check and report the outcome.",
                "observations": ["What changed?", "What was observed?"],
            })),
        ])
        loop = AgentLoop(self.core, MetaProvider(client=first))
        pending = loop.run().session.next_action
        resumed = loop.resume_with_result("Recorded outcome", {"reporter": "user"})
        ref = resumed.session.evidence[-1].id
        hypothesis = self.core.snapshot.hypotheses[0].id
        self.assertEqual(resumed.session.evidence[-1].request_id, pending.id)
        second = FakeClient([
            tool_response(("update_hypothesis", update_args(hypothesis, [ref]))),
            tool_response(("submit_recommendation", {
                "hypothesis_id": hypothesis, "action": "Apply the fix indicated by the evidence.",
                "evidence_ids": [ref], "acknowledged_contradictions": [],
            })),
        ])
        result = AgentLoop(self.core, MetaProvider(client=second)).run()
        self.assertEqual(result.outcome, LoopOutcome.COMPLETED)
        self.assertEqual(result.session.recommendation.evidence_ids, (ref,))

    def test_developer_instruction_and_state_rendering(self):
        ref = self.seed("Controlled check implicates cause A")
        self.core.execute("propose_hypothesis", {"cause": "Cause A"})
        feedback = [StepFeedback(
            tool="propose_hypothesis", ok=True, message="propose_hypothesis succeeded.",
            record_id=self.core.snapshot.hypotheses[0].id,
        )]
        client = FakeClient([text_response()])
        MetaProvider(client=client).decide(self.request_for(feedback=feedback))
        messages = client.completions.calls[0]["messages"]
        self.assertEqual(messages[0]["role"], "developer")
        developer, user = messages[0]["content"], messages[1]["content"]
        for phrase in (
            "uncertainty", "exactly one tool call", "only the supplied tools",
            "Never invent", "authoritative", "insufficient",
            "certainty", "recommendation",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, developer)
        for phrase in (
            PROBLEM, ref, "Controlled check implicates cause A", "Cause A",
            "possible", "propose_hypothesis succeeded", "provider steps remaining",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, user)

    def test_pending_request_rendered_when_present(self):
        self.core.execute("request_user_evidence", {
            "action": "Perform the next check and report the outcome.",
            "observations": ["What changed?"],
        })
        client = FakeClient([text_response()])
        MetaProvider(client=client).decide(self.request_for())
        user = client.completions.calls[0]["messages"][1]["content"]
        self.assertIn("request_user_evidence", user)
        self.assertIn("Perform the next check", user)
        self.assertIn("What changed?", user)

    def test_structured_400_surfaces_validation_details(self):
        error = FakeBadRequestError("Error code: 400")
        error.status_code = 400
        error.body = {"error": {
            "message": "Invalid tools[0]: additional properties not allowed",
            "type": "invalid_request_error", "param": "tools", "code": None,
        }}
        provider = MetaProvider(client=FakeClient([error]))
        with self.assertRaises(ProviderError) as raised:
            provider.decide(self.request_for())
        self.assertEqual(
            str(raised.exception),
            "Meta API rejected request (400 invalid_request_error, param=tools): "
            "Invalid tools[0]: additional properties not allowed",
        )
        self.assertIs(raised.exception.__cause__, error)
        error.body["error"]["code"] = "invalid_tool"
        provider = MetaProvider(client=FakeClient([error]))
        with self.assertRaises(ProviderError) as raised:
            provider.decide(self.request_for())
        self.assertIn("param=tools, code=invalid_tool", str(raised.exception))
        self.assertEqual(self.core.snapshot.turn_count, 0)

    def test_400_with_missing_fields_stays_useful(self):
        cases = [
            ({}, "Meta API rejected request (400)"),
            ({"error": {}}, "Meta API rejected request (400)"),
            (
                {"error": {"message": "Only a message"}},
                "Meta API rejected request (400): Only a message",
            ),
            (
                {"message": "Top-level shape", "type": "invalid_request_error"},
                "Meta API rejected request (400 invalid_request_error): Top-level shape",
            ),
            (
                {"error": {"message": "m", "type": "t", "param": "p", "code": 400}},
                "Meta API rejected request (400 t, param=p, code=400): m",
            ),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                error = FakeBadRequestError("Error code: 400")
                error.status_code = 400
                error.body = body
                provider = MetaProvider(client=FakeClient([error]))
                with self.assertRaises(ProviderError) as raised:
                    provider.decide(self.request_for())
                self.assertEqual(str(raised.exception), expected)
        error = FakeBadRequestError("Error code: 400")
        error.status_code = None
        error.body = {"error": {"message": "No status attached", "type": "invalid_request_error"}}
        provider = MetaProvider(client=FakeClient([error]))
        with self.assertRaises(ProviderError) as raised:
            provider.decide(self.request_for())
        self.assertEqual(
            str(raised.exception),
            "Meta API rejected request (invalid_request_error): No status attached",
        )

    def test_malformed_error_body_safe(self):
        cases = [
            ("plain text failure", "Meta API rejected request (400): plain text failure"),
            (b"bytes failure", "Meta API rejected request (400): bytes failure"),
            (["a list"], "Meta API rejected request (400)"),
            (42, "Meta API rejected request (400)"),
            (None, "Meta API rejected request (400)"),
            (
                {"error": {"message": {"nested": 1}, "type": ["x"], "param": "p", "code": True}},
                "Meta API rejected request (400, param=p)",
            ),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                error = FakeBadRequestError("Error code: 400")
                error.status_code = 400
                error.body = body
                provider = MetaProvider(client=FakeClient([error]))
                with self.assertRaises(ProviderError) as raised:
                    provider.decide(self.request_for())
                self.assertEqual(str(raised.exception), expected)

    def test_provider_error_text_never_includes_credentials(self):
        key = "LLM|999|fake-secret-key-material"
        header = f"Bearer {key}"
        error = FakeBadRequestError(f"request failed for key {key} header {header}")
        error.status_code = 400
        error.body = {"error": {
            "message": "Invalid tools entry", "type": "invalid_request_error",
            "param": "tools", "code": None,
        }}
        error.request = SimpleNamespace(headers={"Authorization": header})
        error.response = SimpleNamespace(status_code=400, text=f"response holding {key}")
        provider = MetaProvider(client=FakeClient([error]))
        with self.assertRaises(ProviderError) as raised:
            provider.decide(self.request_for())
        text = str(raised.exception)
        self.assertNotIn(key, text)
        self.assertNotIn("Bearer", text)
        self.assertNotIn("Authorization", text)
        self.assertIn("Invalid tools entry", text)
        self.assertIn("param=tools", text)
        poisoned = FakeConnectionError(f"connection reset using {key}")
        provider = MetaProvider(client=FakeClient([poisoned]))
        with self.assertRaises(ProviderError) as raised:
            provider.decide(self.request_for())
        self.assertNotIn(key, str(raised.exception))

    def test_image_included_when_provided(self):
        client = FakeClient([text_response()])
        MetaProvider(client=client, image_data_url="data:image/png;base64,AAA").decide(
            self.request_for(),
        )
        content = client.completions.calls[0]["messages"][1]["content"]
        images = [block for block in content if block.get("type") == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["image_url"]["url"], "data:image/png;base64,AAA")

    def test_image_absent_by_default_and_set_image_updates(self):
        client = FakeClient([text_response(), text_response()])
        provider = MetaProvider(client=client)
        provider.decide(self.request_for())
        provider.set_image("data:image/png;base64,BBB")
        provider.decide(self.request_for())
        calls = client.completions.calls
        self.assertIsInstance(calls[0]["messages"][1]["content"], str)
        updated = calls[1]["messages"][1]["content"]
        self.assertEqual(updated[1]["image_url"]["url"], "data:image/png;base64,BBB")

    def test_network_guard_is_active(self):
        with self.assertRaisesRegex(AssertionError, "Network access forbidden"):
            socket.create_connection(("localhost", 1))


if __name__ == "__main__":
    unittest.main()
