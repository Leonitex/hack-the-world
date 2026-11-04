"""Synchronous provider-neutral agent loop around the diagnostic core.

Flow per step: the provider chooses one model-selectable tool call, the
loop validates it structurally, the diagnostic core executes it, and the
real ActionResult or rejection returns to the provider as feedback.

Structural failures never reach DiagnosticSession.execute() and never
consume a core turn. Well-shaped calls that the core rejects do consume a
turn per existing core accounting, and the rejection becomes feedback.

Budgets follow the same split: provider-format/structural errors do not
spend authoritative diagnostic budgets (turns or completion attempts),
while well-shaped semantic failures do. This intentionally differs from
calling the raw core directly, where even malformed submit_recommendation
arguments consume a completion attempt.
"""

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from diagnostic_core.contracts import MODEL_ACTION_FIELDS, validate_arguments
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import ActionResult, Rejected, Session, SessionStatus as S

from .providers import ProviderDecision, ProviderError, ProviderRequest, StepFeedback, ToolCall
from .tools import MODEL_TOOLS, StructuralError, validate_tool_call


class LoopOutcome(StrEnum):
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    PAUSED = "paused"
    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class LoopResult:
    outcome: LoopOutcome
    session: Session
    steps_used: int
    message: str


class AgentLoop:
    """Owns the provider loop for one DiagnosticSession. Single caller only."""

    DEFAULT_MAX_PROVIDER_STEPS = 50
    FEEDBACK_WINDOW = 10

    def __init__(self, session, provider, *, max_provider_steps=DEFAULT_MAX_PROVIDER_STEPS):
        if not isinstance(session, DiagnosticSession):
            raise TypeError("AgentLoop requires a DiagnosticSession")
        if not callable(getattr(provider, "decide", None)):
            raise TypeError("Provider must implement decide(request)")
        if type(max_provider_steps) is not int or max_provider_steps < 1:
            raise Rejected("Provider step budget must be a positive integer")
        self._session = session
        self._provider = provider
        self._max_provider_steps = max_provider_steps
        self._feedback = []
        self._steps_used = 0

    @property
    def session(self):
        return self._session

    @property
    def steps_used(self):
        return self._steps_used

    def run(self):
        """Advance the session until the provider must stop. See LoopOutcome."""
        provider_failed_last = False
        while True:
            snapshot = self._session.snapshot
            if snapshot.status is S.COMPLETED:
                return self._result(LoopOutcome.COMPLETED, snapshot, "Recommendation verified; session completed.")
            if snapshot.status is S.PAUSED:
                return self._result(
                    LoopOutcome.PAUSED, snapshot, f"Session paused: {snapshot.pause_reason}.",
                )
            if snapshot.status is S.NEEDS_INPUT:
                return self._result(
                    LoopOutcome.NEEDS_INPUT, snapshot,
                    "Waiting on a trusted result for the pending request.",
                )
            if snapshot.status is not S.INVESTIGATING:
                raise Rejected(f"Unexpected session status: {snapshot.status}")
            if self._steps_used >= self._max_provider_steps:
                if provider_failed_last:
                    return self._result(
                        LoopOutcome.PROVIDER_ERROR, snapshot,
                        "Provider failures exhausted the step budget.",
                    )
                return self._result(
                    LoopOutcome.BUDGET_EXHAUSTED, snapshot, "Provider step budget exhausted.",
                )
            try:
                decision = self._provider.decide(self._request(snapshot))
            except ProviderError as exc:
                self._note_provider_failure(exc)
                provider_failed_last = True
                continue
            except Exception as exc:
                # A misbehaving provider must not crash the loop or touch state.
                self._note_provider_failure(exc)
                provider_failed_last = True
                continue
            self._steps_used += 1
            provider_failed_last = False
            try:
                name, arguments = self._extract_call(decision)
                validate_tool_call(name, arguments)
                self._assert_model_action(name)
            except StructuralError as exc:
                self._record_feedback(tool=None, ok=False, message=str(exc))
                continue
            try:
                result = self._session.execute(name, arguments)
            except Rejected as exc:
                # A rejection may still exhaust a core limit and pause.
                snapshot = self._session.snapshot
                self._record_feedback(tool=name, ok=False, message=f"{name} rejected: {exc}")
                if snapshot.status is S.PAUSED:
                    return self._result(
                        LoopOutcome.PAUSED, snapshot, f"Session paused: {snapshot.pause_reason}.",
                    )
                continue
            snapshot = result.session
            self._record_success(name, result)
            if snapshot.status is S.NEEDS_INPUT:
                return self._result(
                    LoopOutcome.NEEDS_INPUT, snapshot,
                    "Waiting on a trusted result for the pending request.",
                )
            if snapshot.status is S.COMPLETED:
                return self._result(LoopOutcome.COMPLETED, snapshot, "Recommendation verified; session completed.")
            if snapshot.status is S.PAUSED:
                return self._result(
                    LoopOutcome.PAUSED, snapshot, f"Session paused: {snapshot.pause_reason}.",
                )

    def resume_with_result(self, statement, provenance, *, source="user_text"):
        """Record a trusted real-world result for the pending request.

        The ingestion action is chosen internally from the pending request
        kind; the caller cannot select an arbitrary action or request id.
        Resumes the same diagnostic session. Raises Rejected without
        touching the core when there is no pending request.
        """
        snapshot = self._session.snapshot
        if snapshot.status is not S.NEEDS_INPUT or snapshot.next_action is None:
            raise Rejected("There is no pending input request")
        pending = snapshot.next_action
        if pending.kind == "request_diagnostic_test":
            action, arguments = "record_test_result", {
                "request_id": pending.id, "statement": statement, "provenance": provenance,
            }
        elif pending.kind == "request_user_evidence":
            action, arguments = "provide_user_evidence", {
                "request_id": pending.id, "source": source,
                "statement": statement, "provenance": provenance,
            }
        else:
            raise Rejected(f"Unknown pending request kind: {pending.kind}")
        # Shape-check trusted input with the core's own validator before
        # executing, so malformed UI input is rejected without consuming a
        # diagnostic turn. Session/semantic validity stays authoritative in
        # execute(), which validates again.
        validate_arguments(action, arguments)
        return self._session.execute(action, arguments)

    def _result(self, outcome, snapshot, message):
        return LoopResult(outcome, snapshot, self._steps_used, message)

    def _request(self, snapshot):
        return ProviderRequest(
            problem=snapshot.problem,
            session=snapshot,
            # Isolated copy: a provider must not mutate the shared schemas.
            tools=deepcopy(MODEL_TOOLS),
            feedback=tuple(self._feedback[-self.FEEDBACK_WINDOW:]),
            turn_count=snapshot.turn_count,
            completion_attempts=snapshot.completion_attempts,
            remaining_provider_steps=self._max_provider_steps - self._steps_used,
        )

    @staticmethod
    def _extract_call(decision):
        if not isinstance(decision, ProviderDecision):
            raise StructuralError(
                "Invalid provider decision: expected exactly one tool call, "
                f"got {type(decision).__name__}",
            )
        calls = decision.calls
        if not isinstance(calls, (tuple, list)) or len(calls) != 1:
            size = len(calls) if isinstance(calls, (tuple, list)) else type(calls).__name__
            raise StructuralError(
                f"Invalid provider decision: expected exactly one tool call, got {size}",
            )
        call = calls[0]
        if not isinstance(call, ToolCall):
            raise StructuralError("Invalid provider decision: malformed tool call shape")
        return call.name, call.arguments

    @staticmethod
    def _assert_model_action(name):
        # Independent of validate_tool_call: even if structural validation
        # is bypassed or mistaken, a model-originated action outside
        # MODEL_ACTION_FIELDS never reaches authoritative execution.
        if not isinstance(name, str) or name not in MODEL_ACTION_FIELDS:
            raise StructuralError(f"{name!r} is not a model-selectable action")

    def _note_provider_failure(self, exc):
        self._steps_used += 1
        detail = str(exc) or type(exc).__name__
        self._record_feedback(tool=None, ok=False, message=f"Provider error: {detail}")

    def _record_feedback(self, *, tool, ok, message, record_id=None, verification=None):
        self._feedback.append(StepFeedback(
            tool=tool,
            ok=ok,
            message=message,
            record_id=record_id,
            verification_passed=verification.passed if verification is not None else None,
            verification_issues=verification.issues if verification is not None else (),
        ))

    def _record_success(self, name, result: ActionResult):
        verification = result.verification
        if verification is None:
            self._record_feedback(
                tool=name, ok=True, message=f"{name} succeeded: {result.record_id}.",
                record_id=result.record_id,
            )
        elif verification.passed:
            self._record_feedback(
                tool=name, ok=True, message="Recommendation verified; session completed.",
                verification=verification,
            )
        else:
            issues = "; ".join(verification.issues)
            self._record_feedback(
                tool=name, ok=False,
                message=f"Recommendation rejected by verification: {issues}.",
                verification=verification,
            )
