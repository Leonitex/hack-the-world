"""Issue #9 regression tests: non-repeating diagnosis, honest inconclusive
dispositions, and reopenable technician cases.

Covers M8A trajectory linkage, M8B repetition guards, M8C terminal
inconclusive handling, M8D acceptance scenarios, and M8E case lifecycle
(checkpoints, solve/reopen, restart recovery). Deterministic only: no
network, no credentials.
"""

import json
import os
import sqlite3
import tempfile
import unittest

from agent.loop import AgentLoop, LoopOutcome
from agent.providers import CompletedStep, FakeProvider, ToolCall
from diagnostic_core.contracts import MODEL_ACTION_FIELDS
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import Rejected, SessionStatus as S


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


if __name__ == "__main__":
    unittest.main()
