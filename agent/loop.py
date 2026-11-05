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

Provider steps are bounded twice: each run() call may consume at most
max_advance_steps new steps, while the loop instance may never exceed
max_provider_steps total. A trusted user result therefore grants a fresh
bounded allowance on the next run() while billed work stays capped
session-wide. Spending one advance mid-investigation returns
ADVANCE_EXHAUSTED, which an explicit same-loop retry may continue;
spending the session cap returns BUDGET_EXHAUSTED.

The loop also owns the authoritative trajectory: every core-generated
request linked to the evidence ingested for it. A request repeating an
answered test (exact or near-identical wording) is rejected as
no-progress before reaching the core, and persistent no-progress closes
honestly as inconclusive instead of looping forever.
"""

import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from diagnostic_core.contracts import MODEL_ACTION_FIELDS, is_text, validate_arguments
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import (
    ActionResult, HypothesisStatus as H, Rejected, Session, SessionStatus as S,
)

from .providers import (
    CompletedStep, ProviderDecision, ProviderError, ProviderRequest,
    StepFeedback, ToolCall,
)
from .tools import MODEL_TOOLS, StructuralError, validate_tool_call


class LoopOutcome(StrEnum):
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    INCONCLUSIVE = "inconclusive"
    PAUSED = "paused"
    PROVIDER_ERROR = "provider_error"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ADVANCE_EXHAUSTED = "advance_exhausted"


@dataclass(frozen=True)
class LoopResult:
    outcome: LoopOutcome
    session: Session
    steps_used: int
    message: str
    advance_steps: int = 0


class AgentLoop:
    """Owns the provider loop for one DiagnosticSession. Single caller only."""

    DEFAULT_MAX_PROVIDER_STEPS = 50
    FEEDBACK_WINDOW = 10
    # Consecutive answered-test repeats before the loop closes honestly.
    MAX_CONSECUTIVE_DUPLICATES = 3
    # Consecutive steps without new evidence or verification before ditto.
    MAX_STALE_STEPS = 8
    BOOKKEEPING_VERSION = 1

    def __init__(self, session, provider, *, max_provider_steps=DEFAULT_MAX_PROVIDER_STEPS,
                 max_advance_steps=None):
        if not isinstance(session, DiagnosticSession):
            raise TypeError("AgentLoop requires a DiagnosticSession")
        if not callable(getattr(provider, "decide", None)):
            raise TypeError("Provider must implement decide(request)")
        if type(max_provider_steps) is not int or max_provider_steps < 1:
            raise Rejected("Provider step budget must be a positive integer")
        if max_advance_steps is None:
            max_advance_steps = max_provider_steps
        if type(max_advance_steps) is not int or max_advance_steps < 1:
            raise Rejected("Advance step budget must be a positive integer")
        self._session = session
        self._provider = provider
        self._max_provider_steps = max_provider_steps
        self._max_advance_steps = max_advance_steps
        self._feedback = []
        self._trajectory = []
        self._duplicates = 0
        self._stale = 0
        self._steps_used = 0
        self._run_entry_steps = 0

    @property
    def session(self):
        return self._session

    @property
    def steps_used(self):
        return self._steps_used

    def run(self):
        """Advance the session until the provider must stop. See LoopOutcome."""
        provider_failed_last = False
        self._run_entry_steps = self._steps_used
        advance_cap = self._steps_used + self._max_advance_steps
        while True:
            snapshot = self._session.snapshot
            if snapshot.status is S.COMPLETED:
                return self._result(LoopOutcome.COMPLETED, snapshot, "Recommendation verified; session completed.")
            if snapshot.status is S.INCONCLUSIVE:
                self._reset_progress()
                return self._result(
                    LoopOutcome.INCONCLUSIVE, snapshot,
                    f"Inconclusive: {_report_summary(snapshot)}",
                )
            if snapshot.status is S.PAUSED:
                return self._result(
                    LoopOutcome.PAUSED, snapshot, f"Session paused: {snapshot.pause_reason}.",
                )
            if snapshot.status is S.NEEDS_INPUT:
                self._reset_progress()
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
            if self._steps_used >= advance_cap:
                if provider_failed_last:
                    return self._result(
                        LoopOutcome.PROVIDER_ERROR, snapshot,
                        "Provider failures spent this advance.",
                    )
                return self._result(
                    LoopOutcome.ADVANCE_EXHAUSTED, snapshot,
                    "Advance allowance spent; an explicit retry may continue.",
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
            if name in ("request_diagnostic_test", "request_user_evidence"):
                repeat = _find_repeat(
                    name, arguments, self._trajectory, snapshot.next_action)
                if repeat is not None:
                    self._duplicates += 1
                    self._stale += 1
                    self._record_feedback(tool=name, ok=False, message=repeat)
                    if self._duplicates >= self.MAX_CONSECUTIVE_DUPLICATES:
                        closing = self._try_honest_close("repeat")
                        if closing is not None:
                            return closing
                    continue
            try:
                result = self._session.execute(name, arguments)
            except Rejected as exc:
                # A rejection may still exhaust a core limit and pause.
                after = self._session.snapshot
                self._record_feedback(tool=name, ok=False, message=f"{name} rejected: {exc}")
                if after.status is S.PAUSED:
                    return self._result(
                        LoopOutcome.PAUSED, after, f"Session paused: {after.pause_reason}.",
                    )
                if after.completion_attempts != snapshot.completion_attempts:
                    self._reset_progress()
                else:
                    self._stale += 1
                    if self._stale >= self.MAX_STALE_STEPS:
                        closing = self._try_honest_close("stale")
                        if closing is not None:
                            return closing
                continue
            snapshot = result.session
            self._record_success(name, result)
            if name in ("propose_hypothesis", "update_hypothesis"):
                self._stale += 1
            else:
                self._reset_progress()
            if snapshot.status is S.NEEDS_INPUT:
                return self._result(
                    LoopOutcome.NEEDS_INPUT, snapshot,
                    "Waiting on a trusted result for the pending request.",
                )
            if snapshot.status is S.COMPLETED:
                return self._result(LoopOutcome.COMPLETED, snapshot, "Recommendation verified; session completed.")
            if snapshot.status is S.INCONCLUSIVE:
                return self._result(
                    LoopOutcome.INCONCLUSIVE, snapshot,
                    f"Inconclusive: {_report_summary(snapshot)}",
                )
            if snapshot.status is S.PAUSED:
                return self._result(
                    LoopOutcome.PAUSED, snapshot, f"Session paused: {snapshot.pause_reason}.",
                )
            if self._stale >= self.MAX_STALE_STEPS:
                closing = self._try_honest_close("stale")
                if closing is not None:
                    return closing

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
        result = self._session.execute(action, arguments)
        self._trajectory.append(CompletedStep(
            request_id=pending.id, kind=pending.kind, action=pending.action,
            observations=tuple(pending.observations),
            evidence_id=result.record_id, statement=statement,
        ))
        self._reset_progress()
        return result

    def capture_bookkeeping(self):
        """Export restart-recovery state: billed steps, budgets, trajectory."""
        return {
            "version": self.BOOKKEEPING_VERSION,
            "steps_used": self._steps_used,
            "max_provider_steps": self._max_provider_steps,
            "max_advance_steps": self._max_advance_steps,
            "trajectory": [
                {
                    "request_id": step.request_id, "kind": step.kind,
                    "action": step.action,
                    "observations": list(step.observations),
                    "evidence_id": step.evidence_id,
                    "statement": step.statement,
                }
                for step in self._trajectory
            ],
        }

    def apply_bookkeeping(self, data):
        """Restore bookkeeping onto this loop's session. Rejects tampering.

        Billed steps can never fall below the completed requests they paid
        for, and every trajectory entry must match real session evidence
        (and vice versa), so neither the budget nor the anti-repeat state
        can be quietly dropped on restore.
        """
        if (not isinstance(data, dict) or type(data.get("version")) is not int
                or data["version"] != self.BOOKKEEPING_VERSION):
            raise Rejected("Unsupported loop bookkeeping version")
        for key in ("max_provider_steps", "max_advance_steps"):
            if type(data.get(key)) is not int or data[key] < 1:
                raise Rejected(f"Invalid loop bookkeeping {key}")
        steps = data.get("steps_used")
        if type(steps) is not int or steps < 0 or steps > data["max_provider_steps"]:
            raise Rejected("Invalid loop bookkeeping step count")
        entries = data.get("trajectory")
        if not isinstance(entries, list):
            raise Rejected("Invalid loop bookkeeping trajectory")
        restored = []
        for entry in entries:
            if (not isinstance(entry, dict)
                    or not is_text(entry.get("request_id"))
                    or entry.get("kind") not in {
                        "request_diagnostic_test", "request_user_evidence"}
                    or not is_text(entry.get("action"))
                    or not is_text(entry.get("evidence_id"))
                    or not is_text(entry.get("statement"))):
                raise Rejected("Invalid loop bookkeeping trajectory")
            observations = entry.get("observations")
            if (not isinstance(observations, list) or not observations
                    or any(not is_text(item) for item in observations)):
                raise Rejected("Invalid loop bookkeeping trajectory")
            restored.append(CompletedStep(
                entry["request_id"], entry["kind"], entry["action"],
                tuple(observations), entry["evidence_id"], entry["statement"],
            ))
        if steps < len(restored):
            raise Rejected("Loop bookkeeping steps fall below completed requests")
        seen = set()
        for step in restored:
            key = (step.request_id, step.evidence_id)
            if key in seen:
                raise Rejected("Loop bookkeeping trajectory repeats a request")
            seen.add(key)
        evidence = {item.id: item for item in self._session.snapshot.evidence}
        for step in restored:
            linked = evidence.get(step.evidence_id)
            if (linked is None or linked.request_id != step.request_id
                    or linked.statement != step.statement):
                raise Rejected("Loop bookkeeping trajectory does not match session evidence")
        covered = {(step.request_id, step.evidence_id) for step in restored}
        for item in self._session.snapshot.evidence:
            if item.request_id is not None and (item.request_id, item.id) not in covered:
                raise Rejected("Loop bookkeeping trajectory omits session evidence")
        self._steps_used = steps
        self._max_provider_steps = data["max_provider_steps"]
        self._max_advance_steps = data["max_advance_steps"]
        self._trajectory = restored
        self._run_entry_steps = steps
        self._reset_progress()

    def _result(self, outcome, snapshot, message):
        advance_steps = self._steps_used - self._run_entry_steps
        return LoopResult(outcome, snapshot, self._steps_used, message, advance_steps)

    def _request(self, snapshot):
        return ProviderRequest(
            problem=snapshot.problem,
            session=snapshot,
            # Isolated copy: a provider must not mutate the shared schemas.
            tools=deepcopy(MODEL_TOOLS),
            feedback=tuple(self._feedback[-self.FEEDBACK_WINDOW:]),
            turn_count=snapshot.turn_count,
            completion_attempts=snapshot.completion_attempts,
            remaining_provider_steps=min(
                self._max_provider_steps - self._steps_used,
                self._run_entry_steps + self._max_advance_steps - self._steps_used,
            ),
            # Full answered-test history: never truncated like feedback.
            trajectory=tuple(self._trajectory),
        )

    def _reset_progress(self):
        self._duplicates = 0
        self._stale = 0

    def _try_honest_close(self, reason):
        """Application-originated inconclusive close; None when not applicable.

        Built only from authoritative session records (evidence IDs,
        hypothesis causes), so the handoff can never invent findings.
        Returns None when the core refuses (e.g. wrong status) or when no
        evidence exists to cite; the caller then continues to its budget.
        """
        snapshot = self._session.snapshot
        if not snapshot.evidence:
            return None
        if reason == "repeat":
            summary = (
                "Stopped after the same answered test was requested "
                f"{self._duplicates} more times without progress."
            )
        else:
            summary = (
                f"Stopped after {self._stale} steps without new evidence "
                "or verification."
            )
        open_causes = [
            hypothesis.cause for hypothesis in snapshot.hypotheses
            if hypothesis.status in {H.POSSIBLE, H.SUPPORTED, H.CONFIRMED}
        ]
        try:
            result = self._session.execute("declare_inconclusive", {
                "summary": summary,
                "checked_evidence_ids": [item.id for item in snapshot.evidence],
                "remaining_possibilities": (
                    "; ".join(open_causes)
                    or "No candidate cause was established."
                ),
                "safe_next_steps": _SAFE_NEXT_STEPS,
            })
        except Rejected:
            return None
        self._reset_progress()
        self._record_success("declare_inconclusive", result)
        return self._result(
            LoopOutcome.INCONCLUSIVE, result.session, f"Inconclusive: {summary}")

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
        if name == "declare_inconclusive":
            self._record_feedback(
                tool=name, ok=True,
                message="Investigation declared inconclusive.",
            )
        elif verification is None:
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


_SAFE_NEXT_STEPS = (
    "Re-check the reported results, retry with different parts or "
    "conditions where safe, and if the device still shows no response take "
    "it to a qualified repair technician."
)

_WORDS = re.compile(r"[a-z0-9]+")

# An exact normalized-text match always counts, even across request kinds:
# the user cannot see the kind distinction, only the repeated question.
# Near matches need the same kind plus token overlap: Jaccard at or above
# NEAR_DUPLICATE_SIMILARITY, or containment at or above
# REPEAT_CONTAINMENT with Jaccard at or above
# REPEAT_CONTAINMENT_JACCARD_FLOOR (so padding an answered test with
# filler words cannot evade the guard, while genuinely distinct tests
# with small shared vocabulary still pass).
NEAR_DUPLICATE_SIMILARITY = 0.8
REPEAT_CONTAINMENT = 0.9
REPEAT_CONTAINMENT_JACCARD_FLOOR = 0.6


def _fold_text(text):
    return unicodedata.normalize("NFKC", text).lower()


def _normalize_text(text):
    return " ".join(_WORDS.findall(_fold_text(text)))


def _token_similarity(first, second):
    if first == second:
        return 1.0
    union = first | second
    if not union:
        return 1.0
    return len(first & second) / len(union)


def _token_containment(first, second):
    if first == second:
        return 1.0
    smaller = min(len(first), len(second))
    if not smaller:
        return 1.0
    return len(first & second) / smaller


def _request_tokens(action, observations):
    return set(_WORDS.findall(_fold_text(action + " " + " ".join(observations))))


def _find_repeat(name, arguments, trajectory, pending):
    """Describe the answered/pending request this call repeats, if any."""
    candidates = list(trajectory)
    if pending is not None:
        # Defensive: run() returns on NEEDS_INPUT, so pending is None at the
        # guard today; the check protects future callers that run mid-request.
        candidates.append(pending)
    action = arguments["action"]
    observations = arguments.get("observations", [])
    text_key = (
        _normalize_text(action),
        tuple(sorted(_normalize_text(item) for item in observations)),
    )
    tokens = _request_tokens(action, observations)
    for prior in candidates:
        prior_observations = list(prior.observations)
        prior_text = (
            _normalize_text(prior.action),
            tuple(sorted(_normalize_text(item) for item in prior_observations)),
        )
        if prior_text == text_key:
            return _repeat_message(prior, exact=True)
        if prior.kind == name:
            prior_tokens = _request_tokens(prior.action, prior_observations)
            similarity = _token_similarity(tokens, prior_tokens)
            contained = _token_containment(tokens, prior_tokens)
            if (similarity >= NEAR_DUPLICATE_SIMILARITY
                    or (contained >= REPEAT_CONTAINMENT
                        and similarity >= REPEAT_CONTAINMENT_JACCARD_FLOOR)):
                return _repeat_message(prior, exact=False)
    return None


def _repeat_message(prior, exact):
    match = "repeats" if exact else "nearly repeats"
    answered = getattr(prior, "evidence_id", None)
    if answered is None:
        detail = f"the request {prior.id} already awaiting a result"
    else:
        detail = f"the answered test {prior.request_id} (result {answered})"
    return (
        f"No progress: this request {match} {detail}. The outcome is "
        "already recorded; propose a genuinely different diagnostic step "
        "or declare the investigation inconclusive."
    )


def _report_summary(snapshot):
    report = snapshot.inconclusive
    return report.summary if report is not None else "no detail recorded"
