"""Issue #9 regression tests: non-repeating diagnosis, honest inconclusive
dispositions, and reopenable technician cases.

Covers M8A trajectory linkage, M8B repetition guards, M8C terminal
inconclusive handling, M8D acceptance scenarios, and M8E case lifecycle
(checkpoints, solve/reopen, restart recovery). Deterministic only: no
network, no credentials.
"""

import json
import os
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agent.baseten import SYSTEM_PROMPT as BASETEN_SYSTEM_PROMPT, BasetenMuseProvider
from agent.loop import AgentLoop, LoopOutcome
from agent.meta_provider import DEVELOPER_INSTRUCTION, render_state
from agent.providers import CompletedStep, FakeProvider, ProviderRequest, ToolCall
from agent.tools import MODEL_TOOLS
from diagnostic_core.contracts import MODEL_ACTION_FIELDS
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import Rejected, SessionStatus as S
from history_store import HistoryStore

import phone_app


PROBLEM = "Phone shows no response when the power button is pressed."


def _session_with_evidence():
    session = DiagnosticSession(PROBLEM)
    first = session.execute("record_evidence", {
        "source": "user_text", "statement": PROBLEM,
        "provenance": {"channel": "test", "kind": "initial_problem"},
    })
    return session, first.record_id


def _complete_request_cycle(session, action="Press and hold the power button for ten seconds."):
    req = session.execute("request_diagnostic_test", {
        "action": action, "observations": ["What happened?"],
    })
    result = session.execute("record_test_result", {
        "request_id": req.record_id, "statement": "Nothing happened.",
        "provenance": {"channel": "test", "kind": "observation"},
    })
    return req.record_id, result.record_id


class InconclusiveCoreTests(unittest.TestCase):
    """M8C: honest terminal inconclusive disposition in the core."""

    def test_declare_inconclusive_is_model_selectable(self):
        self.assertIn("declare_inconclusive", MODEL_ACTION_FIELDS)
        fields = MODEL_ACTION_FIELDS["declare_inconclusive"]
        self.assertEqual(
            set(fields),
            {"summary", "checked_evidence_ids", "remaining_possibilities",
             "safe_next_steps"},
        )

    def test_valid_declaration_terminates_honestly(self):
        session, evidence_id = _session_with_evidence()
        result = session.execute("declare_inconclusive", {
            "summary": "Power press and charger check both showed no response; "
                       "no further safe user test can narrow this.",
            "checked_evidence_ids": [evidence_id],
            "remaining_possibilities": "Battery, button, or board failure.",
            "safe_next_steps": "Try a known-good charger, then a repair shop.",
        })
        snapshot = result.session
        self.assertIs(snapshot.status, S.INCONCLUSIVE)
        self.assertIsNotNone(snapshot.inconclusive)
        self.assertEqual(snapshot.inconclusive.checked_evidence_ids, (evidence_id,))
        self.assertIn("charger", snapshot.inconclusive.safe_next_steps)
        self.assertIsNone(snapshot.recommendation)

    def test_declaration_citing_unknown_evidence_is_rejected(self):
        session, _evidence_id = _session_with_evidence()
        with self.assertRaises(Rejected):
            session.execute("declare_inconclusive", {
                "summary": "Nothing conclusive found.",
                "checked_evidence_ids": ["no-such-evidence"],
                "remaining_possibilities": "Unknown.",
                "safe_next_steps": "See a technician.",
            })
        self.assertIs(session.snapshot.status, S.INVESTIGATING)

    def test_declaration_with_empty_checked_list_is_rejected(self):
        session, _evidence_id = _session_with_evidence()
        with self.assertRaises(Rejected):
            session.execute("declare_inconclusive", {
                "summary": "Nothing conclusive found.",
                "checked_evidence_ids": [],
                "remaining_possibilities": "Unknown.",
                "safe_next_steps": "See a technician.",
            })
        self.assertIs(session.snapshot.status, S.INVESTIGATING)

    def test_inconclusive_is_terminal_for_execute(self):
        session, evidence_id = _session_with_evidence()
        session.execute("declare_inconclusive", {
            "summary": "No further narrowing possible.",
            "checked_evidence_ids": [evidence_id],
            "remaining_possibilities": "Hardware fault.",
            "safe_next_steps": "See a technician.",
        })
        with self.assertRaises(Rejected):
            session.execute("propose_hypothesis", {"cause": "Too late."})
        with self.assertRaises(Rejected):
            session.execute("request_diagnostic_test", {
                "action": "Another test.", "observations": ["What?"]})

    def test_declaration_rejected_outside_investigating(self):
        session, evidence_id = _session_with_evidence()
        req = session.execute("request_diagnostic_test", {
            "action": "Press power.", "observations": ["What happened?"]})
        args = {
            "summary": "Cannot declare while waiting.",
            "checked_evidence_ids": [evidence_id],
            "remaining_possibilities": "Unknown.",
            "safe_next_steps": "Wait.",
        }
        with self.assertRaises(Rejected):
            session.execute("declare_inconclusive", args)
        session.execute("record_test_result", {
            "request_id": req.record_id, "statement": "Nothing.",
            "provenance": {"channel": "test", "kind": "observation"},
        })
        session.execute("declare_inconclusive", {
            "summary": "Done.", "checked_evidence_ids": [evidence_id],
            "remaining_possibilities": "Unknown.", "safe_next_steps": "Shop.",
        })
        with self.assertRaises(Rejected):
            session.execute("declare_inconclusive", args)


class ReopenCoreTests(unittest.TestCase):
    """M8E: trusted technician reopening of terminal sessions."""

    def test_reopen_is_trusted_not_model_selectable(self):
        self.assertNotIn("reopen_investigation", MODEL_ACTION_FIELDS)

    def _completed_session(self):
        session, evidence_id = _session_with_evidence()
        hyp = session.execute("propose_hypothesis", {"cause": "Dead battery."})
        session.execute("update_hypothesis", {
            "hypothesis_id": hyp.record_id, "status": "supported",
            "supporting": [evidence_id], "contradicting": [],
            "resolutions": {}, "rationale": "No response at all.",
        })
        session.execute("submit_recommendation", {
            "hypothesis_id": hyp.record_id, "action": "Replace the battery.",
            "evidence_ids": [evidence_id], "acknowledged_contradictions": [],
        })
        self.assertIs(session.snapshot.status, S.COMPLETED)
        return session

    def test_reopen_completed_keeps_prior_recommendation(self):
        session = self._completed_session()
        before = session.snapshot
        session.execute("reopen_investigation", {"reason": "Repair did not fix it."})
        after = session.snapshot
        self.assertIs(after.status, S.INVESTIGATING)
        self.assertEqual(after.recommendation, before.recommendation)
        self.assertEqual(after.verifications, before.verifications)

    def test_reopen_inconclusive_keeps_prior_report(self):
        session, evidence_id = _session_with_evidence()
        session.execute("declare_inconclusive", {
            "summary": "Stuck.", "checked_evidence_ids": [evidence_id],
            "remaining_possibilities": "Board.", "safe_next_steps": "Shop.",
        })
        session.execute("reopen_investigation", {"reason": "New symptom observed."})
        after = session.snapshot
        self.assertIs(after.status, S.INVESTIGATING)
        self.assertIsNotNone(after.inconclusive)

    def test_reopen_rejected_from_active_states(self):
        session, _evidence_id = _session_with_evidence()
        with self.assertRaises(Rejected):
            session.execute("reopen_investigation", {"reason": "No-op."})
        req = session.execute("request_diagnostic_test", {
            "action": "Press power.", "observations": ["What?"]})
        with self.assertRaises(Rejected):
            session.execute("reopen_investigation", {"reason": "No-op."})
        session.execute("record_test_result", {
            "request_id": req.record_id, "statement": "Nothing.",
            "provenance": {"channel": "test", "kind": "observation"},
        })
        with self.assertRaises(Rejected):
            session.execute("reopen_investigation", {"reason": "No-op."})


class CheckpointTests(unittest.TestCase):
    """M8E: versioned validated checkpoints preserve exact session state."""

    def _rich_session(self):
        session, evidence_id = _session_with_evidence()
        hyp = session.execute("propose_hypothesis", {"cause": "Dead battery."})
        request_id, _result_id = _complete_request_cycle(session)
        session.execute("update_hypothesis", {
            "hypothesis_id": hyp.record_id, "status": "weakened",
            "supporting": [], "contradicting": [evidence_id],
            "resolutions": {}, "rationale": "Initial report was vague.",
        })
        session.execute("request_user_evidence", {
            "action": "Describe the charger LED.",
            "observations": ["What color is the charger LED?"],
        })
        return session, evidence_id, hyp.record_id, request_id

    def test_round_trip_preserves_everything(self):
        session, _e, _h, _r = self._rich_session()
        before = session.snapshot
        payload = session.to_checkpoint()
        json.dumps(payload)  # must be JSON-safe
        restored = DiagnosticSession.from_checkpoint(payload)
        after = restored.snapshot
        self.assertEqual(after, before)
        # Counters preserved: both sessions continue the identical ID
        # sequence after the pending request is resolved on each.
        pending = session.snapshot.next_action
        trusted = {
            "request_id": pending.id, "source": "user_text",
            "statement": "The LED is dark.",
            "provenance": {"channel": "t", "kind": "k"},
        }
        session.execute("provide_user_evidence", dict(trusted))
        restored.execute("provide_user_evidence", dict(trusted))
        extra = {
            "source": "user_text", "statement": "extra",
            "provenance": {"channel": "t", "kind": "k"},
        }
        live_next = session.execute("record_evidence", dict(extra)).record_id
        restored_next = restored.execute("record_evidence", dict(extra)).record_id
        self.assertEqual(restored_next, live_next)

    def test_rejects_unknown_version(self):
        session, _e, _h, _r = self._rich_session()
        payload = session.to_checkpoint()
        payload["version"] = 999
        with self.assertRaises(Rejected):
            DiagnosticSession.from_checkpoint(payload)

    def test_rejects_id_prefix_mismatch(self):
        session, _e, _h, _r = self._rich_session()
        payload = session.to_checkpoint()
        payload["evidence"][0]["id"] = "other-session:e1"
        with self.assertRaises(Rejected):
            DiagnosticSession.from_checkpoint(payload)

    def test_rejects_status_incoherence(self):
        session, _e, _h, _r = self._rich_session()
        payload = session.to_checkpoint()
        self.assertEqual(payload["status"], "needs_input")
        payload["next_action"] = None
        with self.assertRaises(Rejected):
            DiagnosticSession.from_checkpoint(payload)

    def test_rejects_counter_regression(self):
        session, _e, _h, _r = self._rich_session()
        payload = session.to_checkpoint()
        payload["request_count"] = 0
        with self.assertRaises(Rejected):
            DiagnosticSession.from_checkpoint(payload)

    def test_rejects_unknown_status(self):
        session, _e, _h, _r = self._rich_session()
        payload = session.to_checkpoint()
        payload["status"] = "teleporting"
        with self.assertRaises(Rejected):
            DiagnosticSession.from_checkpoint(payload)

    def test_round_trip_with_blank_rationale_hypothesis(self):
        session, _evidence_id = _session_with_evidence()
        session.execute("propose_hypothesis", {"cause": "Fresh cause."})
        restored = DiagnosticSession.from_checkpoint(session.to_checkpoint())
        self.assertEqual(restored.snapshot, session.snapshot)

    def test_needs_input_checkpoint_resumes_with_matching_result(self):
        session, _e, _h, _r = self._rich_session()
        restored = DiagnosticSession.from_checkpoint(session.to_checkpoint())
        pending = restored.snapshot.next_action
        result = restored.execute("provide_user_evidence", {
            "request_id": pending.id, "source": "user_text",
            "statement": "The LED is dark.",
            "provenance": {"channel": "t", "kind": "k"},
        })
        self.assertIs(result.session.status, S.INVESTIGATING)


def _loop(problem=PROBLEM, script=(), **kwargs):
    session = DiagnosticSession(problem)
    session.execute("record_evidence", {
        "source": "user_text", "statement": problem,
        "provenance": {"channel": "test", "kind": "initial_problem"},
    })
    provider = FakeProvider(list(script))
    return AgentLoop(session, provider, **kwargs), provider


def _request_call(action, observations=("What happened?",)):
    return ToolCall("request_diagnostic_test", {
        "action": action, "observations": list(observations),
    })


POWER_TEST = "Press and hold the power button for ten seconds."
CHARGER_TEST = "Try a known-good charger in a different wall outlet."


class TrajectoryTests(unittest.TestCase):
    """M8A: the loop captures authoritative request/result pairs."""

    def test_completed_pair_reaches_next_provider_request(self):
        loop, provider = _loop(script=[
            _request_call(POWER_TEST),
            ToolCall("propose_hypothesis", {"cause": "Dead battery."}),
        ])
        first = loop.run()
        self.assertIs(first.outcome, LoopOutcome.NEEDS_INPUT)
        request_id = first.session.next_action.id
        ingested = loop.resume_with_result(
            "Nothing happened. No LED, no fan.",
            {"channel": "test", "kind": "observation"},
        )
        loop.run()
        trajectory = provider.requests[-1].trajectory
        self.assertEqual(len(trajectory), 1)
        step = trajectory[0]
        self.assertIsInstance(step, CompletedStep)
        self.assertEqual(step.request_id, request_id)
        self.assertEqual(step.kind, "request_diagnostic_test")
        self.assertEqual(step.action, POWER_TEST)
        self.assertEqual(step.evidence_id, ingested.record_id)
        self.assertIn("No LED", step.statement)

    def test_trajectory_survives_feedback_window(self):
        script = [_request_call(f"Diagnostic test number {index}.")
                for index in range(12)]
        loop, provider = _loop(script=script)
        for index in range(12):
            result = loop.run()
            self.assertIs(result.outcome, LoopOutcome.NEEDS_INPUT)
            loop.resume_with_result(
                f"Result number {index}.",
                {"channel": "test", "kind": "observation"},
            )
        loop.run()
        trajectory = provider.requests[-1].trajectory
        self.assertEqual(len(trajectory), 12)
        self.assertEqual(trajectory[0].action, "Diagnostic test number 0.")
        self.assertEqual(trajectory[-1].statement, "Result number 11.")


class DuplicateGuardTests(unittest.TestCase):
    """M8B: answered tests are never presented to the user twice."""

    def test_exact_repeat_blocked_before_core(self):
        loop, provider = _loop(script=[
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
            _request_call(CHARGER_TEST),
        ])
        first = loop.run()
        self.assertIs(first.outcome, LoopOutcome.NEEDS_INPUT)
        turns_before = first.session.turn_count
        loop.resume_with_result("Nothing happened.",
                                {"channel": "test", "kind": "observation"})
        turns_after_resume = loop.session.snapshot.turn_count
        second = loop.run()
        self.assertIs(second.outcome, LoopOutcome.NEEDS_INPUT)
        # The duplicate consumed no core turn; the distinct test did.
        self.assertEqual(loop.session.snapshot.turn_count, turns_after_resume + 1)
        self.assertGreater(turns_after_resume, turns_before)
        self.assertEqual(second.session.next_action.action, CHARGER_TEST)
        feedback = provider.requests[-1].feedback[-1]
        self.assertIn("already", feedback.message.lower())

    def test_near_duplicate_synonym_blocked(self):
        loop, _provider = _loop(script=[
            _request_call(POWER_TEST),
            _request_call("Press and hold the power button for 10 seconds!!"),
            _request_call(CHARGER_TEST),
        ])
        loop.run()
        loop.resume_with_result("Nothing happened.",
                                {"channel": "test", "kind": "observation"})
        second = loop.run()
        self.assertIs(second.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(second.session.next_action.action, CHARGER_TEST)

    def test_genuinely_distinct_test_allowed(self):
        loop, _provider = _loop(script=[
            _request_call("Check the power cable connection."),
            _request_call("Check the power button connection."),
        ])
        loop.run()
        loop.resume_with_result("Cable is firmly connected.",
                                {"channel": "test", "kind": "observation"})
        second = loop.run()
        self.assertIs(second.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(
            second.session.next_action.action, "Check the power button connection.")

    def test_grounded_retest_with_new_condition_allowed(self):
        loop, _provider = _loop(script=[
            _request_call(POWER_TEST),
            _request_call(
                "Press and hold the power button for ten seconds while "
                "the known-good charger is connected.",
                observations=("Does any LED blink now?",)),
        ])
        loop.run()
        loop.resume_with_result("Nothing happened.",
                                {"channel": "test", "kind": "observation"})
        second = loop.run()
        self.assertIs(second.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertIn("known-good charger", second.session.next_action.action)

    def test_duplicate_count_resets_after_genuine_progress(self):
        loop, _provider = _loop(script=[
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
            _request_call(CHARGER_TEST),
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
            _request_call("Inspect the charging port for debris."),
        ])
        loop.run()
        loop.resume_with_result("Nothing happened.",
                                {"channel": "test", "kind": "observation"})
        # Two duplicates rejected, then a distinct test proceeds: no
        # auto-inconclusive yet, and the later duplicates start fresh.
        mid = loop.run()
        self.assertIs(mid.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(mid.session.next_action.action, CHARGER_TEST)
        loop.resume_with_result("Still nothing.",
                                {"channel": "test", "kind": "observation"})
        final = loop.run()
        self.assertIs(final.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertIn("debris", final.session.next_action.action)


class AutoInconclusiveTests(unittest.TestCase):
    """M8B/M8C: persistent no-progress ends honestly, never loops."""

    def test_three_repeats_end_inconclusive_with_checked_evidence(self):
        loop, provider = _loop(script=[
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
            _request_call(POWER_TEST),
        ])
        loop.run()
        loop.resume_with_result("Nothing happened. No LED, no fan.",
                                {"channel": "test", "kind": "observation"})
        turns_after_resume = loop.session.snapshot.turn_count
        result = loop.run()
        self.assertIs(result.outcome, LoopOutcome.INCONCLUSIVE)
        self.assertIs(result.session.status, S.INCONCLUSIVE)
        report = result.session.inconclusive
        self.assertIsNotNone(report)
        known = {item.id for item in result.session.evidence}
        self.assertTrue(set(report.checked_evidence_ids) <= known)
        self.assertTrue(report.checked_evidence_ids)
        self.assertIsNone(result.session.recommendation)
        # Duplicates burned no diagnostic turns; only the honest close did.
        self.assertEqual(loop.session.snapshot.turn_count, turns_after_resume + 1)
        self.assertEqual(provider.decide_calls, 4)

    def test_stale_hypothesis_churn_ends_inconclusive(self):
        script = [ToolCall("propose_hypothesis", {"cause": f"Cause {index}."})
                  for index in range(8)]
        loop, _provider = _loop(script=script)
        result = loop.run()
        self.assertIs(result.outcome, LoopOutcome.INCONCLUSIVE)
        self.assertIsNotNone(result.session.inconclusive)
        self.assertIsNone(result.session.recommendation)
        self.assertEqual(result.session.turn_count, 10)

    def test_model_declared_inconclusive_stops_immediately(self):
        session = DiagnosticSession(PROBLEM)
        session.execute("record_evidence", {
            "source": "user_text", "statement": PROBLEM,
            "provenance": {"channel": "test", "kind": "initial_problem"},
        })
        evidence_id = session.snapshot.evidence[0].id
        provider = FakeProvider([
            ToolCall("propose_hypothesis", {"cause": "Dead battery."}),
            ToolCall("declare_inconclusive", {
                "summary": "No safe test can narrow this further.",
                "checked_evidence_ids": [evidence_id],
                "remaining_possibilities": "Board or battery failure.",
                "safe_next_steps": "Take the phone to a repair shop.",
            }),
        ])
        loop = AgentLoop(session, provider)
        result = loop.run()
        self.assertIs(result.outcome, LoopOutcome.INCONCLUSIVE)
        self.assertEqual(provider.decide_calls, 2)
        again = loop.run()
        self.assertIs(again.outcome, LoopOutcome.INCONCLUSIVE)
        self.assertEqual(provider.decide_calls, 2)

    def test_m8d_acceptance_scenario(self):
        """Power press -> nothing; charger check -> nothing; repeat power
        press must replan or end inconclusive, never re-ask or confirm."""
        loop, provider = _loop(script=[
            _request_call(POWER_TEST),
            _request_call(CHARGER_TEST),
            _request_call(POWER_TEST),
            _request_call("press + hold the POWER button for ten seconds"),
            _request_call(POWER_TEST),
        ])
        loop.run()
        loop.resume_with_result("No LED, no fan, nothing at all.",
                                {"channel": "test", "kind": "observation"})
        loop.run()
        loop.resume_with_result("Still no change with the other charger.",
                                {"channel": "test", "kind": "observation"})
        result = loop.run()
        self.assertIs(result.outcome, LoopOutcome.INCONCLUSIVE)
        session = result.session
        self.assertIsNone(session.recommendation)
        self.assertFalse([
            h for h in session.hypotheses if str(h.status) == "confirmed"])
        # Exactly two real requests were ever created; the three repeats
        # burned no turns. Only the honest close added a final turn.
        self.assertEqual(session.turn_count, 6)
        seen = provider.requests[-1].trajectory
        self.assertEqual(len(seen), 2)
        self.assertEqual(len({step.request_id for step in seen}), 2)

    def test_reopen_attempt_by_model_is_structurally_blocked(self):
        loop, provider = _loop(script=[
            ToolCall("reopen_investigation", {"reason": "Model tried."}),
        ])
        before = loop.session.snapshot.turn_count
        result = loop.run()
        self.assertEqual(result.outcome, LoopOutcome.PROVIDER_ERROR)
        self.assertEqual(loop.session.snapshot.turn_count, before)
        structural = provider.requests[1].feedback[0].message
        self.assertIn("never model-callable", structural)


class BookkeepingTests(unittest.TestCase):
    """M8E: loop bookkeeping restores budgets and anti-repeat state."""

    def test_bookkeeping_round_trip_blocks_repeats_after_restore(self):
        loop, _provider = _loop(
            script=[_request_call(POWER_TEST)], max_provider_steps=60,
            max_advance_steps=14)
        loop.run()
        loop.resume_with_result("Nothing happened.",
                                {"channel": "test", "kind": "observation"})
        saved = loop.capture_bookkeeping()
        json.dumps(saved)
        restored_session = DiagnosticSession.from_checkpoint(
            loop.session.to_checkpoint())
        fresh = FakeProvider([_request_call(POWER_TEST), _request_call(CHARGER_TEST)])
        revived = AgentLoop(restored_session, fresh)
        revived.apply_bookkeeping(saved)
        self.assertEqual(revived.steps_used, loop.steps_used)
        result = revived.run()
        self.assertIs(result.outcome, LoopOutcome.NEEDS_INPUT)
        self.assertEqual(result.session.next_action.action, CHARGER_TEST)

    def test_bookkeeping_rejects_budget_reset(self):
        loop, _provider = _loop(script=[_request_call(POWER_TEST)])
        loop.run()
        loop.resume_with_result("Nothing happened.",
                                {"channel": "test", "kind": "observation"})
        saved = loop.capture_bookkeeping()
        self.assertEqual(len(saved["trajectory"]), 1)
        # Billed steps can never drop below the turns actually performed.
        tampered = dict(saved)
        tampered["steps_used"] = 0
        revived = AgentLoop(loop.session, FakeProvider([]))
        with self.assertRaises(Rejected):
            revived.apply_bookkeeping(tampered)
        # ... nor exceed the restored session cap.
        tampered = dict(saved)
        tampered["steps_used"] = tampered["max_provider_steps"] + 1
        with self.assertRaises(Rejected):
            revived.apply_bookkeeping(tampered)

    def test_bookkeeping_rejects_unknown_version(self):
        loop, _provider = _loop(script=[])
        saved = loop.capture_bookkeeping()
        saved["version"] = 999
        with self.assertRaises(Rejected):
            loop.apply_bookkeeping(saved)


class _CannedBasetenResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _request_with_trajectory():
    """A real linked request/result pair plus the provider request for it."""
    loop, provider = _loop(script=[
        _request_call(POWER_TEST),
        ToolCall("propose_hypothesis", {"cause": "Dead battery."}),
    ])
    loop.run()
    loop.resume_with_result("Nothing happened. No LED, no fan.",
                            {"channel": "test", "kind": "observation"})
    loop.run()
    return provider.requests[-1]


class ProviderRenderingTests(unittest.TestCase):
    """M8A/M8B: both providers see completed tests tied to results."""

    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect",
                       "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_meta_renders_completed_test_with_linked_result(self):
        request = _request_with_trajectory()
        text = render_state(request)
        step = request.trajectory[0]
        self.assertIn(POWER_TEST, text)
        self.assertIn("No LED", text)
        self.assertIn(step.request_id, text)
        self.assertIn(step.evidence_id, text)
        self.assertIn(f"via {step.request_id}", text)

    def test_meta_renders_empty_trajectory_explicitly(self):
        session = DiagnosticSession(PROBLEM).snapshot
        request = ProviderRequest(
            problem=PROBLEM, session=session, tools=MODEL_TOOLS, feedback=(),
            turn_count=0, completion_attempts=0, remaining_provider_steps=10,
            trajectory=(),
        )
        self.assertIn("none completed yet", render_state(request))

    def test_meta_instruction_forbids_repeats_and_allows_honest_close(self):
        lowered = DEVELOPER_INSTRUCTION.lower()
        self.assertIn("never request the same or an equivalent test again", lowered)
        self.assertIn("negative observation", lowered)
        self.assertIn("inconclusive", lowered)

    def test_baseten_instruction_carries_completed_history(self):
        request = _request_with_trajectory()
        response = {"choices": [{"message": {"tool_calls": [{
            "id": "call_1", "type": "function", "function": {
                "name": "propose_hypothesis",
                "arguments": json.dumps({"cause": "Cause A"}),
            }}]}}]}
        with patch("urllib.request.urlopen",
                   return_value=_CannedBasetenResponse(response)) as mocked:
            BasetenMuseProvider(api_key="test-key").decide(request)
        sent = json.loads(mocked.call_args.args[0].data.decode("utf-8"))
        user_text = sent["messages"][1]["content"][0]["text"]
        step = request.trajectory[0]
        self.assertIn(POWER_TEST, user_text)
        self.assertIn("No LED", user_text)
        self.assertIn(step.request_id, user_text)
        self.assertIn(step.evidence_id, user_text)

    def test_baseten_system_prompt_forbids_repeats(self):
        lowered = BASETEN_SYSTEM_PROMPT.lower()
        self.assertIn("never request the same test twice", lowered)
        self.assertIn("negative", lowered)


class StoreTests(unittest.TestCase):
    """M8E: checkpoints, case lifecycle, legacy migration."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "history.db")

    def test_checkpoint_round_trip(self):
        store = HistoryStore(self.path)
        store.create_session("s1", "Case 1", PROBLEM)
        bundle = {"version": 1, "session": {"id": "s1"}, "loop": {"steps_used": 3}}
        store.save_checkpoint("s1", bundle)
        self.assertEqual(store.load_checkpoint("s1"), bundle)
        self.assertIsNone(store.load_checkpoint("missing"))

    def test_checkpoint_survives_store_restart(self):
        store = HistoryStore(self.path)
        store.create_session("s1", "Case 1", PROBLEM)
        store.save_checkpoint("s1", {"version": 1})
        reopened = HistoryStore(self.path)
        self.assertEqual(reopened.load_checkpoint("s1"), {"version": 1})
        self.assertEqual(reopened.get_session("s1")["archived"], 0)

    def test_legacy_database_migrates_without_data_loss(self):
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " problem TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'live',"
            " run_token TEXT NOT NULL, created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)")
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " session_id TEXT NOT NULL REFERENCES sessions(id),"
            " seq INTEGER NOT NULL, kind TEXT NOT NULL, glyph TEXT NOT NULL,"
            " title TEXT NOT NULL, detail TEXT NOT NULL, record_id TEXT,"
            " created_at TEXT NOT NULL, UNIQUE (session_id, seq))")
        conn.execute(
            "INSERT INTO sessions (id, name, problem, status, run_token,"
            " created_at, updated_at, archived) VALUES"
            " ('old', 'Old case', 'Old problem', 'live', 'dead-token',"
            " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0)")
        conn.execute(
            "INSERT INTO events (session_id, seq, kind, glyph, title, detail,"
            " record_id, created_at) VALUES ('old', 1, 'note', '*',"
            " 'Old event', 'Kept.', NULL, '2026-01-01T00:00:00+00:00')")
        conn.commit()
        conn.close()
        store = HistoryStore(self.path)
        session = store.get_session("old")
        self.assertEqual(session["case_status"], "open")
        self.assertEqual(session["name"], "Old case")
        events = store.get_events("old")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "Old event")
        # No checkpoint exists, so the stale live row is safely archived.
        self.assertEqual(session["archived"], 1)
        store.save_checkpoint("old", {"version": 1})
        self.assertEqual(store.load_checkpoint("old"), {"version": 1})

    def test_case_status_lifecycle(self):
        store = HistoryStore(self.path)
        store.create_session("s1", "Case 1", PROBLEM)
        self.assertEqual(store.get_session("s1")["case_status"], "open")
        store.set_case_status("s1", "awaiting")
        self.assertEqual(store.get_session("s1")["case_status"], "awaiting")
        store.set_case_status("s1", "inconclusive")
        store.set_case_status("s1", "solved", note="Replaced the battery.")
        solved = store.get_session("s1")
        self.assertEqual(solved["case_status"], "solved")
        self.assertEqual(solved["solved_note"], "Replaced the battery.")
        store.set_case_status("s1", "open")
        reopened = store.get_session("s1")
        self.assertEqual(reopened["case_status"], "open")
        self.assertEqual(reopened["solved_note"], "")
        with self.assertRaises(ValueError):
            store.set_case_status("s1", "teleporting")

    def test_adopt_session_updates_owner(self):
        first = HistoryStore(self.path)
        first.create_session("s1", "Case 1", PROBLEM)
        first.save_checkpoint("s1", {"version": 1})
        second = HistoryStore(self.path)
        second.adopt_session("s1")
        self.assertEqual(second.get_session("s1")["run_token"], second.run_token)


class _StagedFake(FakeProvider):
    def stage(self, *entries):
        self._script.extend(entries)


def _cause(name="Cause A"):
    return ToolCall("propose_hypothesis", {"cause": name})


def _ask(action, observations=("What happened?",)):
    return ToolCall("request_user_evidence", {
        "action": action, "observations": list(observations)})


class AppCaseTests(unittest.TestCase):
    """M8E: reopenable cases, restart recovery, solve/reopen lifecycle."""

    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect",
                       "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_store = phone_app._STORE
        self.db_path = os.path.join(self._tmp.name, "history.db")
        phone_app._STORE = HistoryStore(self.db_path)
        phone_app.STATE["cases"] = {}
        self.client = phone_app.app.test_client()
        self.client.post("/reset")

    def tearDown(self):
        self.client.post("/reset")
        phone_app._STORE = self._old_store

    def start_case(self, problem="The phone shows no response.", script=()):
        fake = _StagedFake(list(script))
        with patch("phone_app.create_provider", return_value=(fake, "Test Provider")):
            response = self.client.post(
                "/start", data={"problem": problem}, follow_redirects=True)
        return response, fake

    def resume(self, answer, case_id=None):
        data = {
            "case_id": case_id or phone_app.STATE["history_session_id"],
            "answer": answer,
        }
        return self.client.post("/resume", data=data, follow_redirects=True)

    def retry(self, case_id=None):
        data = {"case_id": case_id or phone_app.STATE["history_session_id"]}
        return self.client.post("/retry", data=data, follow_redirects=True)

    def simulate_restart(self):
        """Drop all in-memory cases and reopen the same database file."""
        phone_app._STORE = HistoryStore(self.db_path)
        phone_app.STATE["cases"] = {}
        for key in ("loop", "last_result", "error", "provider",
                    "provider_label", "advance_note", "history_session_id",
                    "active_id"):
            phone_app.STATE[key] = None
        phone_app.STATE["images"] = {}
        phone_app.STATE["timeline"] = []
        phone_app.STATE["draft_problem"] = ""
        phone_app.STATE["draft_answer"] = ""

    def test_cases_stay_open_and_switchable(self):
        first, _ = self.start_case(
            script=[_cause("Cause A"), _ask("Check the indicator light.")])
        self.assertIn("Do this next", first.get_data(as_text=True))
        hid_a = phone_app.STATE["history_session_id"]
        self.start_case(problem="Second device is silent.",
                        script=[_cause("Cause B"), _ask("Listen for fan noise.")])
        hid_b = phone_app.STATE["history_session_id"]
        self.assertNotEqual(hid_a, hid_b)
        store = phone_app.get_store()
        self.assertEqual(store.get_session(hid_a)["archived"], 0)
        self.assertEqual(store.get_session(hid_b)["archived"], 0)
        switched = self.client.post(f"/case/{hid_a}/switch", follow_redirects=True)
        self.assertIn("Check the indicator light", switched.get_data(as_text=True))
        snapshot = phone_app.STATE["loop"].session.snapshot
        self.assertEqual(snapshot.id, hid_a)
        self.assertEqual(len(snapshot.evidence), 1)
        self.assertEqual(len(snapshot.hypotheses), 1)

    def test_stale_case_post_rejected_without_mutation(self):
        response_a, _ = self.start_case(
            script=[_cause("Cause A"), _ask("Check the indicator light.")])
        hid_a = phone_app.STATE["history_session_id"]
        self.assertIn("Do this next", response_a.get_data(as_text=True))
        self.start_case(problem="Second device is silent.",
                        script=[_cause("Cause B"), _ask("Listen for fan noise.")])
        hid_b = phone_app.STATE["history_session_id"]
        turns_b = phone_app.STATE["loop"].session.snapshot.turn_count
        response = self.resume("Stale answer for the wrong case.", case_id=hid_a)
        self.assertIn("different case", response.get_data(as_text=True))
        self.assertEqual(phone_app.STATE["history_session_id"], hid_b)
        self.assertEqual(
            phone_app.STATE["loop"].session.snapshot.turn_count, turns_b)
        response = self.client.post(
            "/resume", data={"answer": "Missing case id."}, follow_redirects=True)
        self.assertIn("different case", response.get_data(as_text=True))
        self.assertEqual(
            phone_app.STATE["loop"].session.snapshot.turn_count, turns_b)

    def test_restart_restores_case_with_trajectory_and_budget(self):
        _, fake = self.start_case(
            script=[_cause("Cause A"), _ask("Check the indicator light.")])
        hid = phone_app.STATE["history_session_id"]
        fake.stage(_cause("Cause A2"), _ask("Listen for fan noise."))
        self.resume("The light is dark.")
        steps_before = phone_app.STATE["last_result"].steps_used
        self.assertEqual(phone_app.STATE["last_result"].outcome, LoopOutcome.NEEDS_INPUT)
        self.simulate_restart()
        store = phone_app.get_store()
        self.assertEqual(store.get_session(hid)["archived"], 0)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("open", body)
        restore_fake = _StagedFake([
            _ask("Check the indicator light."),
            _ask("Inspect the charging port for debris."),
        ])
        with patch("phone_app.create_provider",
                   return_value=(restore_fake, "Test Provider")):
            switched = self.client.post(f"/case/{hid}/switch", follow_redirects=True)
            switched_body = switched.get_data(as_text=True)
            self.assertIn("Check the indicator light", switched_body)
            self.assertIn("Session started", switched_body)
            snapshot = phone_app.STATE["loop"].session.snapshot
            self.assertEqual(snapshot.id, hid)
            self.assertEqual(len(snapshot.evidence), 2)
            revived = self.resume("No fan noise at all.")
        final = revived.get_data(as_text=True)
        self.assertIn("Do this next", final)
        self.assertIn("charging port", final)
        self.assertGreaterEqual(
            phone_app.STATE["last_result"].steps_used, steps_before)

    def test_corrupt_checkpoint_fails_safe_with_history_intact(self):
        self.start_case(script=[_cause("Cause A"), _ask("Check the indicator light.")])
        hid = phone_app.STATE["history_session_id"]
        store = phone_app.get_store()
        store.save_checkpoint(hid, {"version": 1, "session": {"bogus": True}, "loop": {}})
        self.simulate_restart()
        response = self.client.post(f"/case/{hid}/switch", follow_redirects=True)
        body = response.get_data(as_text=True)
        self.assertIn("Something needs attention", body)
        self.assertIsNone(phone_app.STATE["loop"])
        live = phone_app.get_store()
        events = live.get_events(hid)
        self.assertTrue(any(e["title"] == "Session started" for e in events))

    def test_solve_reopen_lifecycle_with_completed_case(self):
        _, fake = self.start_case(script=[_cause("Dead battery.")])
        hid = phone_app.STATE["history_session_id"]
        evidence_id = f"{hid}:e1"
        hypothesis_id = f"{hid}:h1"
        fake.stage(
            ToolCall("update_hypothesis", {
                "hypothesis_id": hypothesis_id, "status": "supported",
                "supporting": [evidence_id], "contradicting": [],
                "resolutions": {}, "rationale": "No response at all.",
            }),
            ToolCall("submit_recommendation", {
                "hypothesis_id": hypothesis_id,
                "action": "Replace the battery.",
                "evidence_ids": [evidence_id],
                "acknowledged_contradictions": [],
            }),
        )
        self.retry()
        self.assertEqual(
            phone_app.STATE["last_result"].outcome, LoopOutcome.COMPLETED)
        solved = self.client.post(
            f"/case/{hid}/solve", data={"note": "Battery replaced, device boots."},
            follow_redirects=True,
        )
        self.assertIn("Case solved", solved.get_data(as_text=True))
        self.retry()
        self.assertEqual(phone_app.get_store().get_session(hid)["case_status"], "solved")
        reopened = self.client.post(
            f"/case/{hid}/reopen", data={"note": "Device died again."},
            follow_redirects=True,
        )
        body = reopened.get_data(as_text=True)
        self.assertNotIn("Case solved", body.split("Investigations")[0])
        snapshot = phone_app.STATE["loop"].session.snapshot
        self.assertEqual(snapshot.status, S.INVESTIGATING)
        self.assertIsNotNone(snapshot.recommendation)
        kinds = [e["title"] for e in phone_app.STATE["timeline"]]
        self.assertIn("Marked solved", kinds)
        self.assertIn("Case reopened", kinds)

    def test_inconclusive_handoff_panel_is_honest(self):
        _, fake = self.start_case(script=[_cause("Dead battery.")])
        hid = phone_app.STATE["history_session_id"]
        fake.stage(ToolCall("declare_inconclusive", {
            "summary": "Power and charger checks showed nothing further.",
            "checked_evidence_ids": [f"{hid}:e1"],
            "remaining_possibilities": "Board failure.",
            "safe_next_steps": "Take it to a repair shop.",
        }))
        response = self.retry()
        body = response.get_data(as_text=True)
        self.assertIn("Inconclusive", body)
        self.assertIn("showed nothing further", body)
        self.assertIn("repair shop", body)
        self.assertNotIn("Verified recommendation", body)

    def test_repeat_blocked_across_app_resume(self):
        _, fake = self.start_case(
            script=[_cause("Cause A"), _ask("Check the indicator light.")])
        fake.stage(
            _ask("Check the  indicator light!!"),
            _ask("Inspect the charging port for debris."),
        )
        self.resume("The light is dark.")
        snapshot = phone_app.STATE["loop"].session.snapshot
        self.assertEqual(snapshot.next_action.action,
                         "Inspect the charging port for debris.")

    def test_checkpoint_holds_no_secrets_or_photos(self):
        self.start_case(script=[_cause("Cause A"), _ask("Check the indicator light.")])
        hid = phone_app.STATE["history_session_id"]
        bundle = phone_app.get_store().load_checkpoint(hid)
        self.assertEqual(
            set(bundle),
            {"version", "session", "loop", "timeline", "provider_label",
             "last_outcome", "advance_note", "draft_answer"},
        )
        blob = json.dumps(bundle).lower()
        for marker in ("api_key", "apikey", "secret", "token", "data:image"):
            self.assertNotIn(marker, blob)

    def test_archived_case_is_read_only_without_resume(self):
        self.start_case(script=[_cause("Cause A"), _ask("Check the indicator light.")])
        hid = phone_app.STATE["history_session_id"]
        store = phone_app.get_store()
        store.archive_session(hid)
        self.simulate_restart()
        response = self.client.get(f"/history/{hid}")
        body = response.get_data(as_text=True)
        self.assertIn("archived · read-only", body)
        self.assertNotIn("Resume investigation", body)
        switched = self.client.post(f"/case/{hid}/switch", follow_redirects=True)
        self.assertIn("archived · read-only", switched.get_data(as_text=True))
        self.assertIsNone(phone_app.STATE["loop"])


if __name__ == "__main__":
    unittest.main()
