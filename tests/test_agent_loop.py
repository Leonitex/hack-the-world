"""Mocked agent-loop tests. Any attempted socket connection fails."""

import json
from pathlib import Path
import re
import socket
import unittest
from unittest.mock import patch

from agent import (
    AgentLoop, FakeProvider, LoopOutcome, MODEL_TOOLS, ProviderDecision,
    ProviderError, StructuralError, ToolCall, validate_tool_call,
)
from agent.tools import FIELD_DESCRIPTIONS, TOOL_DESCRIPTIONS
from diagnostic_core import DiagnosticSession, Rejected
from diagnostic_core.contracts import MODEL_ACTION_FIELDS, TRUSTED_INGESTION_ACTION_FIELDS
from diagnostic_core.models import HypothesisStatus as H, Session, SessionStatus as S


PROBLEM = "Unit under test fails its power-on check."

BANNED_SCENARIO_TOKENS = re.compile(
    r"\b(no[_-]?display|display|ram|reseat\w*|cables?|gpu|monitors?|fans?|"
    r"leds?|beeps?|screens?|pixels?|keyboards?|printers?|cartridges?|"
    r"motherboards?|psus?)\b",
    re.IGNORECASE,
)


# Warning: the *_args helpers below normalize shapes via list()/dict(), so they
# cannot express malformed payloads (e.g. a string where a list belongs).
# Tests needing raw malformed values must build their dicts directly.
def update_args(hypothesis_id, status="supported", supporting=(), contradicting=(), resolutions=None):
    return {
        "hypothesis_id": hypothesis_id, "status": status,
        "supporting": list(supporting), "contradicting": list(contradicting),
        "resolutions": dict(resolutions or {}),
        "rationale": "Assessment follows the recorded observations.",
    }


def request_args(action="Perform the next check and report the outcome."):
    return {"action": action, "observations": ["What changed?", "What was observed?"]}


def recommend_args(hypothesis_id, refs=(), acknowledge=()):
    return {
        "hypothesis_id": hypothesis_id, "action": "Apply the fix indicated by the evidence.",
        "evidence_ids": list(refs), "acknowledged_contradictions": list(acknowledge),
    }


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network access forbidden in agent tests"))
            guard.start()
            self.addCleanup(guard.stop)
        self.core = DiagnosticSession(PROBLEM)

    def seed(self, statement="Initial observation", core=None):
        return (core or self.core).execute("record_evidence", {
            "source": "user_text", "statement": statement, "provenance": {"reporter": "user"},
        }).record_id

    def support_call(self, ref):
        def choose(request):
            hypothesis = request.session.hypotheses[0].id
            return ToolCall("update_hypothesis", update_args(hypothesis, "supported", [ref]))
        return choose

    def recommend_call(self, refs):
        def choose(request):
            hypothesis = request.session.hypotheses[0].id
            return ToolCall("submit_recommendation", recommend_args(hypothesis, refs))
        return choose

    def test_tool_names_equal_model_action_fields(self):
        names = [tool["name"] for tool in MODEL_TOOLS]
        self.assertEqual(set(names), set(MODEL_ACTION_FIELDS))
        self.assertEqual(len(names), len(MODEL_ACTION_FIELDS))

    def test_tool_schema_metadata_matches_contracts(self):
        for tool in MODEL_TOOLS:
            with self.subTest(tool=tool["name"]):
                parameters = tool["parameters"]
                expected = set(MODEL_ACTION_FIELDS[tool["name"]])
                self.assertEqual(parameters["type"], "object")
                self.assertFalse(parameters["additionalProperties"])
                self.assertEqual(set(parameters["required"]), expected)
                self.assertEqual(set(parameters["properties"]), expected)
                self.assertTrue(tool["description"].strip())
                for field, schema in parameters["properties"].items():
                    self.assertTrue(schema["description"].strip(), field)
        status_schema = next(
            tool["parameters"]["properties"]["status"] for tool in MODEL_TOOLS
            if tool["name"] == "update_hypothesis"
        )
        self.assertEqual(status_schema["enum"], [status.value for status in H])
        json.dumps(MODEL_TOOLS)

    def test_tool_descriptions_cover_every_contract_field(self):
        for action, fields in MODEL_ACTION_FIELDS.items():
            with self.subTest(action=action):
                self.assertIn(action, TOOL_DESCRIPTIONS)
                for field in fields:
                    self.assertIn((action, field), FIELD_DESCRIPTIONS)

    def test_trusted_ingestion_absent_from_model_tools(self):
        names = {tool["name"] for tool in MODEL_TOOLS}
        for action in TRUSTED_INGESTION_ACTION_FIELDS:
            with self.subTest(action=action):
                self.assertNotIn(action, names)

    def test_trusted_ingestion_calls_blocked_before_core(self):
        calls = {
            "record_evidence": {
                "source": "user_text", "statement": "Invented observation",
                "provenance": {"reporter": "user"},
            },
            "record_test_result": {
                "request_id": "request1", "statement": "Invented result",
                "provenance": {"reporter": "user"},
            },
            "provide_user_evidence": {
                "request_id": "request1", "source": "user_text",
                "statement": "Invented observation", "provenance": {"reporter": "user"},
            },
        }
        for action, arguments in calls.items():
            with self.subTest(action=action):
                with self.assertRaises(StructuralError):
                    validate_tool_call(action, arguments)
                core = DiagnosticSession(PROBLEM)
                provider = FakeProvider([ToolCall(action, arguments)] * 3)
                result = AgentLoop(core, provider, max_provider_steps=3).run()
                self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
                self.assertEqual(provider.decide_calls, 3)
                self.assertEqual(core.snapshot.turn_count, 0)
                self.assertEqual(core.snapshot.evidence, ())
                blocked = provider.requests[1].feedback[-1]
                self.assertFalse(blocked.ok)
                self.assertIn("never model-callable", blocked.message)

    def test_malformed_calls_bounded_without_mutation(self):
        bad_refs = update_args("missing")
        bad_refs["supporting"] = "nope"
        script = [
            "not-a-decision",
            None,
            ProviderDecision(()),
            ProviderDecision((
                ToolCall("propose_hypothesis", {"cause": "Cause A"}),
                ToolCall("propose_hypothesis", {"cause": "Cause B"}),
            )),
            [
                ToolCall("propose_hypothesis", {"cause": "Cause A"}),
                ToolCall("propose_hypothesis", {"cause": "Cause B"}),
            ],
            ToolCall("complete", {"status": "completed"}),
            ToolCall("propose_hypothesis", {"wrong": "field"}),
            ToolCall("propose_hypothesis", {"cause": "  "}),
            ToolCall("propose_hypothesis", "cause"),
            ToolCall("update_hypothesis", bad_refs),
            ToolCall("update_hypothesis", update_args("missing", status="certain")),
            ToolCall(123, {}),
            {"name": "propose_hypothesis", "arguments": {"cause": "Cause A"}},
        ]
        provider = FakeProvider(script)
        loop = AgentLoop(self.core, provider, max_provider_steps=len(script))
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(provider.decide_calls, len(script))
        self.assertEqual(self.core.snapshot.turn_count, 0)
        self.assertEqual(self.core.snapshot.evidence, ())
        self.assertEqual(self.core.snapshot.hypotheses, ())
        self.assertEqual(self.core.snapshot.completion_attempts, 0)
        self.assertEqual(self.core.snapshot.verifications, ())
        with self.assertRaises(StructuralError):
            validate_tool_call("update_hypothesis", update_args("missing", status="certain"))

    def test_semantic_failures_reach_core_and_return_feedback(self):
        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
            ToolCall("update_hypothesis", update_args("missing-id")),
            ToolCall("propose_hypothesis", {"cause": "Cause B"}),
        ])
        loop = AgentLoop(self.core, provider, max_provider_steps=3)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(self.core.snapshot.turn_count, 3)
        self.assertEqual(len(self.core.snapshot.hypotheses), 2)
        rejection = provider.requests[2].feedback[-1]
        self.assertEqual(rejection.tool, "update_hypothesis")
        self.assertFalse(rejection.ok)
        self.assertIn("Unknown hypothesis", rejection.message)

    def test_invalid_transition_reaches_core(self):
        ref = self.seed("Controlled check implicates cause A")

        def regress(request):
            hypothesis = request.session.hypotheses[0].id
            return ToolCall("update_hypothesis", update_args(hypothesis, "possible"))

        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
            self.support_call(ref),
            regress,
            ToolCall("propose_hypothesis", {"cause": "Cause B"}),
        ])
        loop = AgentLoop(self.core, provider, max_provider_steps=4)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(self.core.snapshot.turn_count, 5)
        rejection = provider.requests[3].feedback[-1]
        self.assertFalse(rejection.ok)
        self.assertIn("Invalid hypothesis transition", rejection.message)

    def test_successful_multi_step_loop(self):
        ref = self.seed("Controlled check implicates cause A")
        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
            self.support_call(ref),
            self.recommend_call([ref]),
        ])
        loop = AgentLoop(self.core, provider, max_provider_steps=10)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.COMPLETED)
        self.assertEqual(loop.steps_used, 3)
        self.assertEqual(result.session.recommendation.evidence_ids, (ref,))
        self.assertEqual(provider.requests[0].tools, MODEL_TOOLS)
        self.assertIsNot(provider.requests[0].tools, MODEL_TOOLS)
        self.assertEqual(
            [request.remaining_provider_steps for request in provider.requests], [10, 9, 8],
        )

    def test_provider_request_contents(self):
        ref = self.seed()
        self.core.execute("propose_hypothesis", {"cause": "Cause A"})
        provider = FakeProvider([ToolCall("propose_hypothesis", {"cause": "Cause B"})])
        before = self.core.snapshot
        AgentLoop(self.core, provider, max_provider_steps=1).run()
        request = provider.requests[0]
        self.assertEqual(request.problem, PROBLEM)
        self.assertIsInstance(request.session, Session)
        self.assertEqual(request.session, before)
        self.assertEqual(request.turn_count, 2)
        self.assertEqual(request.completion_attempts, 0)
        self.assertIn(ref, [item.id for item in request.session.evidence])

    def test_needs_input_stops_provider_immediately(self):
        provider = FakeProvider([
            ToolCall("request_user_evidence", request_args()),
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
        ])
        loop = AgentLoop(self.core, provider)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(provider.decide_calls, 1)
        self.assertEqual(result.session.status, S.NEEDS_INPUT)
        self.assertIsNotNone(result.session.next_action)
        again = loop.run()
        self.assertEqual(again.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(provider.decide_calls, 1)

    def test_trusted_result_resumes_same_session(self):
        for kind in ("request_diagnostic_test", "request_user_evidence"):
            with self.subTest(kind=kind):
                core = DiagnosticSession(PROBLEM)
                provider = FakeProvider([ToolCall(kind, request_args())])
                loop = AgentLoop(core, provider)
                pending = loop.run().session.next_action
                resumed = loop.resume_with_result("Recorded outcome", {"reporter": "user"})
                self.assertEqual(resumed.session.id, core.snapshot.id)
                self.assertEqual(resumed.session.status, S.INVESTIGATING)
                evidence = resumed.session.evidence[-1]
                self.assertEqual(evidence.request_id, pending.id)
                expected = "diagnostic_test" if kind == "request_diagnostic_test" else "user_text"
                self.assertEqual(evidence.source, expected)
                follow = AgentLoop(
                    core, FakeProvider([ToolCall("propose_hypothesis", {"cause": "Cause A"})]),
                    max_provider_steps=1,
                )
                follow.run()
                self.assertEqual(len(core.snapshot.hypotheses), 1)

    def test_resume_without_pending_request_rejected(self):
        loop = AgentLoop(self.core, FakeProvider([]))
        before = self.core.snapshot
        with self.assertRaises(Rejected):
            loop.resume_with_result("Unsolicited", {"reporter": "user"})
        self.assertEqual(self.core.snapshot, before)
        with self.assertRaises(TypeError):
            loop.resume_with_result("Unsolicited", {"reporter": "user"}, action="record_evidence")

    def test_verification_failure_returned_and_corrected(self):
        support = self.seed("Check implicates cause A")
        other = self.seed("Unrelated observation")
        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
            self.support_call(support),
            self.recommend_call([other]),
            self.recommend_call([support]),
        ])
        result = AgentLoop(self.core, provider, max_provider_steps=10).run()
        self.assertEqual(result.outcome, LoopOutcome.COMPLETED)
        self.assertEqual(result.session.completion_attempts, 2)
        failed = provider.requests[3].feedback[-1]
        self.assertEqual(failed.tool, "submit_recommendation")
        self.assertFalse(failed.ok)
        self.assertFalse(failed.verification_passed)
        self.assertTrue(failed.verification_issues)
        self.assertIn("cite support", failed.message)

    def test_provider_failure_leaves_session_intact(self):
        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
            ProviderError("boom"),
            RuntimeError("unexpected"),
            ProviderError("boom"),
        ])
        loop = AgentLoop(self.core, provider, max_provider_steps=4)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.PROVIDER_ERROR)
        self.assertEqual(self.core.snapshot.turn_count, 1)
        self.assertEqual(len(self.core.snapshot.hypotheses), 1)
        self.assertEqual(self.core.snapshot.status, S.INVESTIGATING)
        healthy = AgentLoop(
            self.core, FakeProvider([ToolCall("propose_hypothesis", {"cause": "Cause B"})]),
            max_provider_steps=1,
        )
        healthy.run()
        self.assertEqual(len(self.core.snapshot.hypotheses), 2)

    def test_provider_cannot_mutate_session(self):
        def mutate(request):
            request.session.status = S.COMPLETED

        core = DiagnosticSession(PROBLEM)
        provider = FakeProvider([mutate, mutate])
        result = AgentLoop(core, provider, max_provider_steps=2).run()
        self.assertEqual(result.outcome, LoopOutcome.PROVIDER_ERROR)
        self.assertEqual(core.snapshot.turn_count, 0)
        self.assertEqual(core.snapshot.status, S.INVESTIGATING)

    def test_provider_retry_exhaustion_bounded(self):
        provider = FakeProvider([ProviderError("down")] * 100)
        loop = AgentLoop(self.core, provider, max_provider_steps=4)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.PROVIDER_ERROR)
        self.assertEqual(provider.decide_calls, 4)
        self.assertEqual(loop.steps_used, 4)
        self.assertEqual(self.core.snapshot.turn_count, 0)

    def test_feedback_window_bounded(self):
        provider = FakeProvider(["garbage"] * 15)
        AgentLoop(self.core, provider, max_provider_steps=15).run()
        self.assertEqual(len(provider.requests[-1].feedback), AgentLoop.FEEDBACK_WINDOW)

    def test_core_turn_limit_surfaces_as_paused(self):
        core = DiagnosticSession(PROBLEM, max_turns=2)
        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
            ToolCall("propose_hypothesis", {"cause": "Cause B"}),
            ToolCall("propose_hypothesis", {"cause": "Cause C"}),
        ])
        result = AgentLoop(core, provider, max_provider_steps=10).run()
        self.assertEqual(result.outcome, LoopOutcome.PAUSED)
        self.assertEqual(result.session.pause_reason, "turn_limit")
        self.assertEqual(provider.decide_calls, 2)

    def test_core_completion_limit_surfaces_as_paused(self):
        core = DiagnosticSession(PROBLEM, max_completion_attempts=1)
        provider = FakeProvider([
            ToolCall("submit_recommendation", recommend_args("missing", ["missing"])),
        ])
        result = AgentLoop(core, provider, max_provider_steps=10).run()
        self.assertEqual(result.outcome, LoopOutcome.PAUSED)
        self.assertEqual(result.session.pause_reason, "completion_attempt_limit")
        self.assertEqual(result.session.completion_attempts, 1)

    def test_rejected_action_can_pause_via_reread(self):
        core = DiagnosticSession(PROBLEM, max_turns=1)
        provider = FakeProvider([ToolCall("update_hypothesis", update_args("missing"))])
        result = AgentLoop(core, provider, max_provider_steps=10).run()
        self.assertEqual(result.outcome, LoopOutcome.PAUSED)
        self.assertEqual(result.session.pause_reason, "turn_limit")
        self.assertEqual(result.session.turn_count, 1)

    def test_constructor_guards(self):
        provider = FakeProvider([])
        with self.assertRaises(TypeError):
            AgentLoop("not-a-session", provider)
        with self.assertRaises(TypeError):
            AgentLoop(self.core, object())
        for budget in (0, -1, True, 1.5, "3"):
            with self.subTest(budget=budget), self.assertRaises(Rejected):
                AgentLoop(self.core, provider, max_provider_steps=budget)

    def test_no_scenario_logic_in_agent_code(self):
        root = Path(__file__).resolve().parent.parent / "agent"
        for path in sorted(root.glob("*.py")):
            with self.subTest(path=path.name):
                hits = BANNED_SCENARIO_TOKENS.findall(path.read_text(encoding="utf-8"))
                self.assertEqual(hits, [])
        self.assertIn("MODEL_ACTION_FIELDS", (root / "tools.py").read_text(encoding="utf-8"))

    def test_malformed_resume_rejected_before_core(self):
        for kind in ("request_diagnostic_test", "request_user_evidence"):
            with self.subTest(kind=kind):
                core = DiagnosticSession(PROBLEM)
                loop = AgentLoop(core, FakeProvider([ToolCall(kind, request_args())]))
                pending = loop.run().session.next_action
                turns = core.snapshot.turn_count
                for statement, provenance in (
                    ("  ", {"reporter": "user"}),
                    ("Recorded outcome", {}),
                    ("Recorded outcome", {"reporter": ""}),
                    ("Recorded outcome", "not-a-dict"),
                ):
                    with self.subTest(statement=statement, provenance=provenance):
                        with self.assertRaises(Rejected):
                            loop.resume_with_result(statement, provenance)
                self.assertEqual(core.snapshot.turn_count, turns)
                self.assertEqual(core.snapshot.status, S.NEEDS_INPUT)
                self.assertEqual(core.snapshot.next_action, pending)
                resumed = loop.resume_with_result("Recorded outcome", {"reporter": "user"})
                self.assertEqual(resumed.session.id, core.snapshot.id)
                self.assertEqual(resumed.session.status, S.INVESTIGATING)

    def test_malformed_resume_source_rejected_before_core(self):
        core = DiagnosticSession(PROBLEM)
        loop = AgentLoop(core, FakeProvider([ToolCall("request_user_evidence", request_args())]))
        loop.run()
        turns = core.snapshot.turn_count
        with self.assertRaises(Rejected):
            loop.resume_with_result("Recorded outcome", {"reporter": "user"}, source="  ")
        self.assertEqual(core.snapshot.turn_count, turns)
        self.assertEqual(core.snapshot.status, S.NEEDS_INPUT)
        resumed = loop.resume_with_result("Recorded outcome", {"reporter": "user"})
        self.assertEqual(resumed.session.status, S.INVESTIGATING)

    def test_malformed_submit_blocked_without_spending_budgets(self):
        # The core increments turn_count on every execute() call and records a
        # completion attempt inside every submit_recommendation, so unchanged
        # counters plus an empty verification history prove execute() was
        # never reached -- without mocks. This intentionally differs from the
        # raw core, which spends a completion attempt on malformed submits.
        bad_refs = recommend_args("missing", ["missing"])
        bad_refs["acknowledged_contradictions"] = "nope"
        provider = FakeProvider([
            ToolCall("submit_recommendation", {"hypothesis_id": "missing"}),
            ToolCall("submit_recommendation", bad_refs),
        ])
        loop = AgentLoop(self.core, provider, max_provider_steps=2)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.BUDGET_EXHAUSTED)
        self.assertEqual(self.core.snapshot.turn_count, 0)
        self.assertEqual(self.core.snapshot.completion_attempts, 0)
        self.assertEqual(self.core.snapshot.verifications, ())
        self.assertEqual(self.core.snapshot.status, S.INVESTIGATING)
        follow = AgentLoop(
            self.core, FakeProvider([ToolCall("propose_hypothesis", {"cause": "Cause A"})]),
            max_provider_steps=1,
        )
        follow.run()
        self.assertEqual(len(self.core.snapshot.hypotheses), 1)

    def test_provider_cannot_mutate_shared_schemas(self):
        def vandalize(request):
            request.tools[0]["name"] = "record_evidence"
            request.tools[0]["parameters"]["required"] = []
            request.tools[0]["parameters"]["properties"] = {}
            return ToolCall("propose_hypothesis", {"cause": "Cause A"})

        before = json.dumps(MODEL_TOOLS)
        provider = FakeProvider([
            vandalize, ToolCall("propose_hypothesis", {"cause": "Cause B"}),
        ])
        AgentLoop(self.core, provider, max_provider_steps=2).run()
        self.assertEqual(provider.requests[0].tools[0]["name"], "record_evidence")
        self.assertEqual(provider.requests[1].tools, MODEL_TOOLS)
        self.assertEqual(json.dumps(MODEL_TOOLS), before)
        self.assertIsNot(provider.requests[0].tools, MODEL_TOOLS)
        self.assertIsNot(provider.requests[0].tools, provider.requests[1].tools)
        self.assertEqual(len(self.core.snapshot.hypotheses), 2)

    def test_run_on_completed_makes_no_provider_calls(self):
        ref = self.seed("Controlled check implicates cause A")
        self.core.execute("propose_hypothesis", {"cause": "Cause A"})
        hypothesis = self.core.snapshot.hypotheses[0].id
        self.core.execute("update_hypothesis", update_args(hypothesis, "supported", [ref]))
        self.core.execute("submit_recommendation", recommend_args(hypothesis, [ref]))
        self.assertEqual(self.core.snapshot.status, S.COMPLETED)
        provider = FakeProvider([ToolCall("propose_hypothesis", {"cause": "Cause B"})])
        result = AgentLoop(self.core, provider).run()
        self.assertEqual(result.outcome, LoopOutcome.COMPLETED)
        self.assertEqual(provider.decide_calls, 0)

    def test_run_on_paused_makes_no_provider_calls(self):
        core = DiagnosticSession(PROBLEM, max_turns=1)
        self.seed("Only observation", core=core)
        self.assertEqual(core.snapshot.status, S.PAUSED)
        provider = FakeProvider([ToolCall("propose_hypothesis", {"cause": "Cause A"})])
        result = AgentLoop(core, provider).run()
        self.assertEqual(result.outcome, LoopOutcome.PAUSED)
        self.assertEqual(provider.decide_calls, 0)

    def test_diagnostic_test_request_stops_immediately(self):
        provider = FakeProvider([
            ToolCall("request_diagnostic_test", request_args()),
            ToolCall("propose_hypothesis", {"cause": "Cause A"}),
        ])
        loop = AgentLoop(self.core, provider)
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(provider.decide_calls, 1)
        self.assertEqual(result.session.next_action.kind, "request_diagnostic_test")
        again = loop.run()
        self.assertEqual(again.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(provider.decide_calls, 1)

    def test_network_guard_is_active(self):
        with self.assertRaisesRegex(AssertionError, "Network access forbidden"):
            socket.create_connection(("localhost", 1))


if __name__ == "__main__":
    unittest.main()
