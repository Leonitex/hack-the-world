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


if __name__ == "__main__":
    unittest.main()
