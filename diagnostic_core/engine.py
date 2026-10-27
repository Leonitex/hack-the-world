"""Synchronous state owner. No model loop, IO, provider, or persistence."""

from dataclasses import replace
from uuid import uuid4

from .contracts import is_text, validate_arguments
from .models import (
    ActionResult, Evidence, Hypothesis, HypothesisStatus as H, InputRequest,
    Recommendation, Rejected, Session, SessionStatus as S, Verification,
)
from .verification import verify_hypothesis, verify_recommendation


class DiagnosticSession:
    """Use execute() for actions and snapshot for read-only results.

    Limits are application configuration, never tool arguments. Rejected actions
    consume turns but do not partially change diagnostic records. Paused and
    completed sessions are terminal in this milestone.
    """

    def __init__(self, problem: str, *, max_turns: int = 50, max_completion_attempts: int = 3):
        if not is_text(problem):
            raise Rejected("A problem statement is required")
        if any(type(n) is not int or n < 1 for n in (max_turns, max_completion_attempts)):
            raise Rejected("Limits must be positive integers")
        self.__state = Session(id=str(uuid4()), problem=problem)
        self.__max_turns = max_turns
        self.__max_completion_attempts = max_completion_attempts
        self.__request_count = 0

    @property
    def snapshot(self):
        return self.__state

    def execute(self, action: str, arguments: dict) -> ActionResult:
        state = self.__state
        if state.status in {S.COMPLETED, S.PAUSED, S.AWAITING_VERIFICATION}:
            raise Rejected(f"Session is {state.status}")
        self.__state = replace(state, turn_count=state.turn_count + 1)
        result = None
        try:
            if state.status == S.NEEDS_INPUT:
                if action not in ("record_test_result", "provide_user_evidence"):
                    raise Rejected("Supply evidence for the pending request before continuing")
            elif action in ("record_test_result", "provide_user_evidence"):
                raise Rejected("There is no pending input request")
            if action == "submit_recommendation":
                result = self.__complete(arguments)
            else:
                args = validate_arguments(action, arguments)
                result = self.__dispatch(action, args)
        finally:
            # Every attempted action is bounded, including malformed calls.
            if (self.__state.turn_count >= self.__max_turns
                    and self.__state.status not in {S.COMPLETED, S.PAUSED}):
                self.__state = replace(self.__state, status=S.PAUSED, pause_reason="turn_limit")
        return replace(result, session=self.__state)

    def __dispatch(self, action, args):
        state = self.__state
        if action == "record_evidence":
            return self.__record(**args)
        if action == "propose_hypothesis":
            hypothesis = Hypothesis(id=self.__id("h", len(state.hypotheses) + 1), **args)
            self.__state = replace(state, hypotheses=state.hypotheses + (hypothesis,))
            return ActionResult(self.__state, hypothesis.id)
        if action == "update_hypothesis":
            return self.__update(args)
        if action in ("request_diagnostic_test", "request_user_evidence"):
            self.__request_count += 1
            request = InputRequest(
                self.__id("request", self.__request_count), action,
                args["action"], args["observations"],
            )
            self.__state = replace(state, status=S.NEEDS_INPUT, next_action=request)
            return ActionResult(self.__state, request.id)
        request = state.next_action
        expected = ("record_test_result" if request.kind == "request_diagnostic_test"
                    else "provide_user_evidence")
        if action != expected or args["request_id"] != request.id:
            raise Rejected("Result does not match the pending request")
        if action == "record_test_result":
            args["source"] = "diagnostic_test"
        result = self.__record(**args)
        self.__state = replace(self.__state, status=S.INVESTIGATING, next_action=None)
        return replace(result, session=self.__state)

    def __id(self, kind, number):
        return f"{self.__state.id}:{kind}{number}"

    def __record(self, source, statement, provenance, request_id=None):
        state = self.__state
        order = len(state.evidence) + 1
        evidence = Evidence(self.__id("e", order), source, statement, provenance, order, request_id)
        self.__state = replace(state, evidence=state.evidence + (evidence,))
        return ActionResult(self.__state, evidence.id)

    def __update(self, args):
        state = self.__state
        old = next((h for h in state.hypotheses if h.id == args["hypothesis_id"]), None)
        if old is None:
            raise Rejected("Unknown hypothesis")
        try:
            status = H(args["status"])
        except ValueError as exc:
            raise Rejected("Unknown hypothesis status") from exc
        resolutions = dict(old.resolutions)
        resolutions.update(args["resolutions"])
        new = replace(
            old, status=status, rationale=args["rationale"],
            supporting=tuple(dict.fromkeys(old.supporting + args["supporting"])),
            contradicting=tuple(dict.fromkeys(old.contradicting + args["contradicting"])),
            resolutions=tuple(sorted(resolutions.items())),
            eliminated_at=(len(state.evidence) if status == H.ELIMINATED and old.status != H.ELIMINATED
                           else old.eliminated_at),
        )
        verify_hypothesis(state, old, new)
        self.__state = replace(state, hypotheses=tuple(new if h.id == old.id else h for h in state.hypotheses))
        return ActionResult(self.__state, new.id)

    def __complete(self, arguments):
        state = replace(
            self.__state, status=S.AWAITING_VERIFICATION,
            completion_attempts=self.__state.completion_attempts + 1,
        )
        self.__state = state
        candidate = None
        try:
            args = validate_arguments("submit_recommendation", arguments)
            candidate = Recommendation(**args)
            issues = verify_recommendation(state, candidate)
        except Rejected as exc:
            issues = (str(exc),)
        verification = Verification(state.completion_attempts, not issues, issues, candidate)
        if not issues:
            state = replace(state, status=S.COMPLETED, recommendation=candidate)
        elif state.completion_attempts >= self.__max_completion_attempts:
            state = replace(state, status=S.PAUSED, pause_reason="completion_attempt_limit")
        else:
            # Failure feedback permits a corrected attempt or a concrete needs_input request.
            state = replace(state, status=S.INVESTIGATING)
        self.__state = replace(state, verifications=state.verifications + (verification,))
        return ActionResult(self.__state, verification=verification)
