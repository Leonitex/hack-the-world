"""Local invariant and contract tests. Any attempted socket connection fails."""

from dataclasses import FrozenInstanceError, replace
import socket
import unittest
from unittest.mock import patch

from diagnostic_core import DiagnosticSession, Rejected
from diagnostic_core.contracts import ACTION_FIELDS, MODEL_ACTION_FIELDS, TRUSTED_INGESTION_ACTION_FIELDS
from diagnostic_core.models import HypothesisStatus as H, SessionStatus as S


PROBLEM = "Computer powers on and fans spin, but there is no display."


class CoreTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(target, side_effect=AssertionError("Network access forbidden in core tests"))
            guard.start()
            self.addCleanup(guard.stop)
        self.core = DiagnosticSession(PROBLEM)

    def evidence(self, text="Fans spin", core=None, source="user_text"):
        return (core or self.core).execute("record_evidence", {
            "source": source, "statement": text, "provenance": {"reporter": "user"},
        }).record_id

    def hypothesis(self, cause="RAM connection", core=None):
        return (core or self.core).execute("propose_hypothesis", {"cause": cause}).record_id

    def update(self, hypothesis, status, support=(), contradict=(), resolutions=None):
        return self.core.execute("update_hypothesis", {
            "hypothesis_id": hypothesis, "status": status,
            "supporting": list(support), "contradicting": list(contradict),
            "resolutions": resolutions or {}, "rationale": "Observed test result changes the assessment.",
        })

    def recommend(self, hypothesis, refs=(), acknowledge=(), core=None):
        return (core or self.core).execute("submit_recommendation", {
            "hypothesis_id": hypothesis, "action": "Check the identified connection.",
            "evidence_ids": list(refs), "acknowledged_contradictions": list(acknowledge),
        })

    def request(self, kind="request_user_evidence", core=None):
        return (core or self.core).execute(kind, {
            "action": "Report the display behavior with a known-good cable.",
            "observations": ["Did an image appear?", "Did the diagnostic LED change?"],
        }).record_id

    def respond(self, request_id, core=None):
        return (core or self.core).execute("provide_user_evidence", {
            "request_id": request_id, "source": "user_text",
            "statement": "No change", "provenance": {"reporter": "user"},
        })

    def test_session_creation(self):
        state = self.core.snapshot
        self.assertEqual(state.problem, PROBLEM)
        self.assertEqual(state.status, S.INVESTIGATING)
        self.assertEqual((state.turn_count, state.completion_attempts), (0, 0))
        self.assertEqual((state.evidence, state.hypotheses), ((), ()))
        self.assertNotEqual(state.id, DiagnosticSession(PROBLEM).snapshot.id)

    def test_model_action_enumeration_excludes_trusted_ingestion(self):
        self.assertEqual(set(MODEL_ACTION_FIELDS), {
            "propose_hypothesis", "update_hypothesis", "request_diagnostic_test",
            "request_user_evidence", "submit_recommendation",
        })
        for action in ("record_evidence", "record_test_result", "provide_user_evidence"):
            with self.subTest(action=action):
                self.assertNotIn(action, MODEL_ACTION_FIELDS)

    def test_action_exposure_groups_do_not_overlap(self):
        self.assertTrue(MODEL_ACTION_FIELDS.keys().isdisjoint(TRUSTED_INGESTION_ACTION_FIELDS))

    def test_every_action_has_exactly_one_exposure_class(self):
        self.assertEqual(set(ACTION_FIELDS), set(MODEL_ACTION_FIELDS) | set(TRUSTED_INGESTION_ACTION_FIELDS))
        for action in ACTION_FIELDS:
            with self.subTest(action=action):
                self.assertEqual(
                    int(action in MODEL_ACTION_FIELDS) + int(action in TRUSTED_INGESTION_ACTION_FIELDS), 1,
                )

    def test_trusted_ingestion_actions_remain_valid_through_application_api(self):
        self.assertEqual(set(TRUSTED_INGESTION_ACTION_FIELDS), {
            "record_evidence", "record_test_result", "provide_user_evidence",
        })
        initial = self.evidence("Initial user observation")
        test_request = self.request("request_diagnostic_test")
        test_result = self.core.execute("record_test_result", {
            "request_id": test_request, "statement": "Display appeared",
            "provenance": {"performed_by": "user"},
        })
        user_request = self.request()
        user_result = self.respond(user_request)
        self.assertEqual([e.id for e in user_result.session.evidence], [
            initial, test_result.record_id, user_result.record_id,
        ])
        self.assertEqual([e.source for e in user_result.session.evidence], [
            "user_text", "diagnostic_test", "user_text",
        ])
        self.assertEqual(user_result.session.status, S.INVESTIGATING)

    def test_invalid_session_configuration(self):
        for problem in ("", " ", None, 5):
            with self.subTest(problem=problem), self.assertRaises(Rejected):
                DiagnosticSession(problem)
        for limit in (0, -1, True, 1.5, "2"):
            for name in ("max_turns", "max_completion_attempts"):
                with self.subTest(limit=limit, name=name), self.assertRaises(Rejected):
                    DiagnosticSession(PROBLEM, **{name: limit})

    def test_evidence_ids_order_and_provenance(self):
        metadata = {"reporter": "user", "capture": "observation-1"}
        first = self.core.execute("record_evidence", {
            "source": "image_observation", "statement": "Diagnostic LED is lit", "provenance": metadata,
        }).record_id
        metadata["reporter"] = "mutated"
        second = self.evidence()
        self.assertNotEqual(first, second)
        self.assertEqual([e.order for e in self.core.snapshot.evidence], [1, 2])
        self.assertEqual(self.core.snapshot.evidence[0].source, "image_observation")
        self.assertEqual(dict(self.core.snapshot.evidence[0].provenance)["reporter"], "user")
        self.assertEqual(self.core.snapshot.evidence[0].id, first)

    def test_multiple_competing_hypotheses(self):
        for cause in ("RAM connection", "Display cable", "GPU connection", "Monitor input"):
            self.hypothesis(cause)
        hypotheses = self.core.snapshot.hypotheses
        self.assertEqual(len({h.id for h in hypotheses}), 4)
        self.assertTrue(all(h.status == H.POSSIBLE for h in hypotheses))

    def test_support_then_strengthen_preserves_prior_evidence(self):
        hypothesis = self.hypothesis()
        first, second = self.evidence("RAM LED lit"), self.evidence("Display returned after reseating")
        self.update(hypothesis, "supported", [first])
        self.update(hypothesis, "supported", [second])
        self.assertEqual(self.core.snapshot.hypotheses[0].supporting, (first, second))

    def test_weaken_then_eliminate_keeps_competing_hypothesis(self):
        hypothesis = self.hypothesis("Display cable")
        other = self.hypothesis("RAM connection")
        ref = self.evidence("Known-good cable also has no display")
        self.update(hypothesis, "weakened", contradict=[ref])
        self.assertEqual(self.core.snapshot.hypotheses[0].status, H.WEAKENED)
        self.update(hypothesis, "eliminated")
        self.assertEqual(self.core.snapshot.hypotheses[0].status, H.ELIMINATED)
        self.assertEqual(self.core.snapshot.hypotheses[1].id, other)
        self.assertEqual(self.core.snapshot.hypotheses[1].status, H.POSSIBLE)

    def test_nonexistent_support_and_contradiction_rejected_atomically(self):
        hypothesis = self.hypothesis()
        before = self.core.snapshot.hypotheses
        for status, support, contra in (("supported", ["missing"], []), ("weakened", [], ["missing"])):
            with self.subTest(status=status), self.assertRaises(Rejected):
                self.update(hypothesis, status, support, contra)
        self.assertEqual(self.core.snapshot.hypotheses, before)

    def test_cross_session_evidence_rejected(self):
        foreign = self.evidence(core=DiagnosticSession("Another device"))
        hypothesis = self.hypothesis()
        with self.assertRaises(Rejected):
            self.update(hypothesis, "supported", [foreign])
        self.assertFalse(self.recommend(hypothesis, [foreign]).verification.passed)

    def test_confirmation_without_support_rejected(self):
        hypothesis = self.hypothesis()
        with self.assertRaises(Rejected):
            self.update(hypothesis, "confirmed")
        self.assertEqual(self.core.snapshot.hypotheses[0].status, H.POSSIBLE)

    def test_valid_evidence_backed_confirmation(self):
        hypothesis = self.hypothesis()
        ref = self.evidence("Repeated reseating test restored display")
        self.update(hypothesis, "confirmed", [ref])
        self.assertEqual(self.core.snapshot.hypotheses[0].status, H.CONFIRMED)

    def test_contradictions_block_confirmation_even_when_omitted_from_update(self):
        hypothesis = self.hypothesis()
        contra = self.evidence("Reseating did not help")
        support = self.evidence("Later controlled test suggests RAM")
        self.update(hypothesis, "weakened", contradict=[contra])
        with self.assertRaises(Rejected):
            self.update(hypothesis, "confirmed", [support])
        self.assertEqual(self.core.snapshot.hypotheses[0].contradicting, (contra,))

    def test_resolution_preserves_contradiction_and_allows_confirmation(self):
        hypothesis = self.hypothesis()
        contra = self.evidence("Initial reseating did not help")
        self.update(hypothesis, "weakened", contradict=[contra])
        support = self.evidence("Controlled retest restored display; initial test used the wrong slot")
        self.update(hypothesis, "confirmed", [support], resolutions={contra: support})
        state = self.core.snapshot.hypotheses[0]
        self.assertEqual(state.status, H.CONFIRMED)
        self.assertEqual(state.contradicting, (contra,))
        self.assertEqual(state.resolutions, ((contra, support),))

    def test_resolution_requires_later_linked_support(self):
        hypothesis = self.hypothesis()
        support = self.evidence("Early observation")
        contra = self.evidence("Contradicting observation")
        self.update(hypothesis, "weakened", [support], [contra])
        for resolution in ({contra: support}, {contra: "missing"}, {"missing": support}):
            with self.subTest(resolution=resolution), self.assertRaises(Rejected):
                self.update(hypothesis, "confirmed", resolutions=resolution)

    def test_same_evidence_cannot_support_and_contradict(self):
        hypothesis = self.hypothesis()
        ref = self.evidence()
        with self.assertRaises(Rejected):
            self.update(hypothesis, "supported", [ref], [ref])

    def test_weakening_and_elimination_require_contradictions(self):
        hypothesis = self.hypothesis()
        for status in ("weakened", "eliminated"):
            with self.subTest(status=status), self.assertRaises(Rejected):
                self.update(hypothesis, status)

    def test_eliminated_cannot_jump_to_confirmed_even_with_new_support(self):
        hypothesis = self.hypothesis()
        contra = self.evidence("Test contradicted RAM explanation")
        self.update(hypothesis, "eliminated", contradict=[contra])
        support = self.evidence("New test supports RAM explanation")
        with self.assertRaises(Rejected):
            self.update(hypothesis, "confirmed", [support], resolutions={contra: support})
        self.assertEqual(self.core.snapshot.hypotheses[0].status, H.ELIMINATED)

    def test_reopening_requires_support_recorded_after_elimination(self):
        hypothesis = self.hypothesis()
        old = self.evidence("Previously available support")
        contra = self.evidence("Contradicting test")
        self.update(hypothesis, "eliminated", contradict=[contra])
        with self.assertRaises(Rejected):
            self.update(hypothesis, "supported", [old])
        fresh = self.evidence("New controlled retest")
        self.update(hypothesis, "supported", [fresh], resolutions={contra: fresh})
        self.update(hypothesis, "confirmed")
        self.assertEqual(self.core.snapshot.hypotheses[0].status, H.CONFIRMED)

    def test_unknown_hypothesis_and_status_rejected(self):
        hypothesis = self.hypothesis()
        for identifier, status in (("missing", "possible"), (hypothesis, "certain")):
            with self.subTest(identifier=identifier, status=status), self.assertRaises(Rejected):
                self.update(identifier, status)

    def test_invalid_state_regression_rejected(self):
        hypothesis = self.hypothesis()
        self.update(hypothesis, "supported", [self.evidence()])
        with self.assertRaises(Rejected):
            self.update(hypothesis, "possible")

    def test_missing_and_invalid_recommendation_evidence_rejected(self):
        hypothesis = self.hypothesis()
        self.update(hypothesis, "supported", [self.evidence()])
        for refs in ([], ["missing"]):
            with self.subTest(refs=refs):
                result = self.recommend(hypothesis, refs)
                self.assertFalse(result.verification.passed)
                self.assertIsNone(result.session.recommendation)
                self.assertEqual(result.session.status, S.INVESTIGATING)

    def test_recommendation_must_cite_selected_hypothesis_support(self):
        hypothesis = self.hypothesis()
        support, unrelated = self.evidence("RAM test"), self.evidence("Fans spin")
        self.update(hypothesis, "supported", [support])
        self.assertFalse(self.recommend(hypothesis, [unrelated]).verification.passed)

    def test_possible_or_unknown_hypothesis_cannot_complete(self):
        hypothesis, ref = self.hypothesis(), self.evidence()
        for identifier in (hypothesis, "missing"):
            with self.subTest(identifier=identifier):
                self.assertFalse(self.recommend(identifier, [ref]).verification.passed)

    def test_valid_recommendation_always_runs_verification(self):
        hypothesis, ref = self.hypothesis(), self.evidence("Controlled test restored display")
        self.update(hypothesis, "confirmed", [ref])
        from diagnostic_core.verification import verify_recommendation
        with patch("diagnostic_core.engine.verify_recommendation", wraps=verify_recommendation) as gate:
            result = self.recommend(hypothesis, [ref])
            gate.assert_called_once()
            self.assertEqual(gate.call_args.args[0].status, S.AWAITING_VERIFICATION)
        self.assertTrue(result.verification.passed)
        self.assertEqual(result.session.status, S.COMPLETED)
        self.assertEqual(result.session.recommendation.evidence_ids, (ref,))
        self.assertEqual(result.session.verifications, (result.verification,))

    def test_recommendation_surfaces_unresolved_contradictions(self):
        hypothesis = self.hypothesis()
        support, contra = self.evidence("Support"), self.evidence("Contradiction")
        self.update(hypothesis, "supported", [support], [contra])
        self.assertFalse(self.recommend(hypothesis, [support]).verification.passed)
        result = self.recommend(hypothesis, [support], [contra])
        self.assertTrue(result.verification.passed)
        self.assertEqual(result.session.hypotheses[0].status, H.SUPPORTED)
        self.assertEqual(result.session.recommendation.acknowledged_contradictions, (contra,))

    def test_insufficient_evidence_can_handoff_then_resume_same_session(self):
        hypothesis = self.hypothesis()
        original = self.core.snapshot
        self.assertFalse(self.recommend(hypothesis).verification.passed)
        request = self.request()
        self.assertEqual(self.core.snapshot.status, S.NEEDS_INPUT)
        result = self.respond(request)
        self.assertEqual(result.session.status, S.INVESTIGATING)
        self.assertEqual(result.session.id, original.id)
        self.assertEqual(result.session.hypotheses, original.hypotheses)
        self.assertIsNone(result.session.next_action)
        self.assertEqual(result.session.evidence[-1].request_id, request)
        self.assertEqual(result.session.completion_attempts, 1)

    def test_diagnostic_test_result_records_provenance_and_resumes(self):
        request = self.request("request_diagnostic_test")
        result = self.core.execute("record_test_result", {
            "request_id": request, "statement": "Display appeared",
            "provenance": {"performed_by": "user", "method": "known-good cable"},
        })
        evidence = result.session.evidence[-1]
        self.assertEqual(evidence.source, "diagnostic_test")
        self.assertEqual(evidence.request_id, request)
        self.assertEqual(dict(evidence.provenance)["method"], "known-good cable")
        self.assertEqual(result.session.status, S.INVESTIGATING)

    def test_wrong_stale_or_unsolicited_result_rejected(self):
        with self.assertRaises(Rejected):
            self.respond("missing")
        request = self.request()
        with self.assertRaises(Rejected):
            self.respond("wrong")
        self.assertEqual(self.core.snapshot.next_action.id, request)
        self.respond(request)
        with self.assertRaises(Rejected):
            self.respond(request)
        self.assertEqual(len(self.core.snapshot.evidence), 1)

    def test_handoff_rejects_wrong_result_kind_and_other_actions(self):
        request = self.request("request_diagnostic_test")
        with self.assertRaises(Rejected):
            self.respond(request)
        with self.assertRaises(Rejected):
            self.evidence()
        with self.assertRaises(Rejected):
            self.recommend("missing")
        self.assertEqual(self.core.snapshot.status, S.NEEDS_INPUT)
        self.assertEqual(self.core.snapshot.evidence, ())

    def test_request_ids_are_unique_and_stale_response_does_not_resume(self):
        first = self.request()
        self.respond(first)
        second = self.request()
        self.assertNotEqual(first, second)
        with self.assertRaises(Rejected):
            self.respond(first)
        self.assertEqual(self.core.snapshot.next_action.id, second)

    def test_completion_attempts_are_bounded_and_audited(self):
        core = DiagnosticSession(PROBLEM, max_completion_attempts=2)
        first = self.recommend("missing", core=core)
        second = self.recommend("missing", core=core)
        self.assertEqual(first.session.status, S.INVESTIGATING)
        self.assertEqual(second.session.status, S.PAUSED)
        self.assertEqual(second.session.pause_reason, "completion_attempt_limit")
        with self.assertRaises(Rejected):
            self.recommend("missing", core=core)
        self.assertEqual(core.snapshot.completion_attempts, 2)
        self.assertEqual(len(core.snapshot.verifications), 2)

    def test_malformed_recommendations_consume_completion_budget(self):
        core = DiagnosticSession(PROBLEM, max_completion_attempts=2)
        for args in ({}, {"verified": True}):
            result = core.execute("submit_recommendation", args)
            self.assertFalse(result.verification.passed)
            self.assertIsNone(result.verification.candidate)
        self.assertEqual(core.snapshot.status, S.PAUSED)

    def test_turns_bound_successful_and_rejected_actions(self):
        for valid in (True, False):
            with self.subTest(valid=valid):
                core = DiagnosticSession(PROBLEM, max_turns=2)
                for _ in range(2):
                    if valid:
                        self.evidence(core=core)
                    else:
                        with self.assertRaises(Rejected):
                            core.execute("bypass", {})
                self.assertEqual(core.snapshot.turn_count, 2)
                self.assertEqual(core.snapshot.status, S.PAUSED)
                self.assertEqual(core.snapshot.pause_reason, "turn_limit")
                with self.assertRaises(Rejected):
                    self.evidence(core=core)
                self.assertEqual(core.snapshot.turn_count, 2)

    def test_completion_on_last_turn_stays_completed(self):
        self.core = DiagnosticSession(PROBLEM, max_turns=4)
        hypothesis, ref = self.hypothesis(), self.evidence()
        self.update(hypothesis, "supported", [ref])
        self.assertEqual(self.recommend(hypothesis, [ref]).session.status, S.COMPLETED)

    def test_resume_does_not_reset_turn_budget(self):
        core = DiagnosticSession(PROBLEM, max_turns=3)
        self.evidence(core=core)
        request = self.request(core=core)
        result = self.respond(request, core=core)
        self.assertEqual(result.session.turn_count, 3)
        self.assertEqual(result.session.status, S.PAUSED)
        self.assertEqual(len(result.session.evidence), 2)

    def test_completed_session_rejects_mutation(self):
        hypothesis, ref = self.hypothesis(), self.evidence()
        self.update(hypothesis, "supported", [ref])
        self.recommend(hypothesis, [ref])
        before = self.core.snapshot
        with self.assertRaises(Rejected):
            self.evidence()
        self.assertEqual(self.core.snapshot, before)

    def test_state_snapshots_cannot_mutate_authoritative_state(self):
        before = self.core.snapshot
        with self.assertRaises(FrozenInstanceError):
            before.status = S.COMPLETED
        with self.assertRaises(AttributeError):
            self.core.snapshot = replace(before, status=S.COMPLETED)
        forged = replace(before, status=S.COMPLETED)
        self.assertNotEqual(self.core.snapshot, forged)
        self.evidence()
        self.assertEqual(before.evidence, ())

    def test_direct_completion_and_verifier_bypass_rejected(self):
        for action in ("complete", "verify", "set_status", "restore_session"):
            with self.subTest(action=action), self.assertRaises(Rejected):
                self.core.execute(action, {"status": "completed", "verified": True})
        self.assertEqual(self.core.snapshot.status, S.INVESTIGATING)
        self.assertIsNone(self.core.snapshot.recommendation)

    def test_invalid_contract_arguments_do_not_insert_evidence(self):
        base = {"source": "user_text", "statement": "Observed", "provenance": {"reporter": "user"}}
        invalid = [None, {}, {**base, "verified": True}, {**base, "source": " "},
                   {**base, "provenance": {}}, {**base, "provenance": {"reporter": []}}]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(Rejected):
                self.core.execute("record_evidence", args)
        self.assertEqual(self.core.snapshot.evidence, ())

    def test_malformed_reference_lists_are_rejected(self):
        hypothesis = self.hypothesis()
        for refs in ("not-a-list", ["x", "x"], [[]], [None]):
            with self.subTest(refs=refs), self.assertRaises(Rejected):
                self.core.execute("update_hypothesis", {
                    "hypothesis_id": hypothesis, "status": "supported", "supporting": refs,
                    "contradicting": [], "resolutions": {}, "rationale": "Test",
                })

    def test_core_handles_an_unrelated_problem(self):
        core = DiagnosticSession("Printer leaves blank pages")
        hypothesis = self.hypothesis("Empty cartridge", core=core)
        evidence = self.evidence("Cartridge reports empty", core=core)
        core.execute("update_hypothesis", {
            "hypothesis_id": hypothesis, "status": "supported", "supporting": [evidence],
            "contradicting": [], "resolutions": {}, "rationale": "Supply indicator matches symptom",
        })
        self.assertTrue(self.recommend(hypothesis, [evidence], core=core).verification.passed)

    def test_network_guard_is_active(self):
        with self.assertRaisesRegex(AssertionError, "Network access forbidden"):
            socket.create_connection(("localhost", 1))


if __name__ == "__main__":
    unittest.main()
