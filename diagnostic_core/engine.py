"""Synchronous state owner. No model loop, IO, provider, or persistence."""

from dataclasses import replace
from uuid import uuid4

from .contracts import is_text, validate_arguments
from .models import (
    ActionResult, Evidence, Hypothesis, HypothesisStatus as H, InconclusiveReport,
    InputRequest, Recommendation, Rejected, Session, SessionStatus as S, Verification,
)
from .verification import (
    verify_hypothesis, verify_inconclusive, verify_recommendation,
)

CHECKPOINT_VERSION = 1


class DiagnosticSession:
    """Use execute() for actions and snapshot for read-only results.

    Limits are application configuration, never tool arguments. Rejected actions
    consume turns but do not partially change diagnostic records. Paused
    sessions are terminal; completed and inconclusive sessions reopen only via
    the trusted reopen_investigation action. to_checkpoint/from_checkpoint
    export and restore validated state without IO; storage lives outside.
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

    def to_checkpoint(self):
        """Export versioned JSON-safe state for restart recovery. No IO."""
        state = self.__state
        return {
            "version": CHECKPOINT_VERSION,
            "id": state.id,
            "problem": state.problem,
            "status": state.status.value,
            "turn_count": state.turn_count,
            "completion_attempts": state.completion_attempts,
            "evidence": [
                {
                    "id": item.id, "source": item.source,
                    "statement": item.statement,
                    "provenance": [list(pair) for pair in item.provenance],
                    "order": item.order, "request_id": item.request_id,
                }
                for item in state.evidence
            ],
            "hypotheses": [
                {
                    "id": item.id, "cause": item.cause,
                    "status": item.status.value,
                    "supporting": list(item.supporting),
                    "contradicting": list(item.contradicting),
                    "resolutions": [list(pair) for pair in item.resolutions],
                    "rationale": item.rationale,
                    "eliminated_at": item.eliminated_at,
                }
                for item in state.hypotheses
            ],
            "next_action": (
                None if state.next_action is None else {
                    "id": state.next_action.id, "kind": state.next_action.kind,
                    "action": state.next_action.action,
                    "observations": list(state.next_action.observations),
                }
            ),
            "recommendation": _recommendation_dict(state.recommendation),
            "verifications": [
                {
                    "attempt": item.attempt, "passed": item.passed,
                    "issues": list(item.issues),
                    "candidate": _recommendation_dict(item.candidate),
                }
                for item in state.verifications
            ],
            "inconclusive": (
                None if state.inconclusive is None else {
                    "summary": state.inconclusive.summary,
                    "checked_evidence_ids": list(state.inconclusive.checked_evidence_ids),
                    "remaining_possibilities": state.inconclusive.remaining_possibilities,
                    "safe_next_steps": state.inconclusive.safe_next_steps,
                }
            ),
            "pause_reason": state.pause_reason,
            "request_count": self.__request_count,
            "max_turns": self.__max_turns,
            "max_completion_attempts": self.__max_completion_attempts,
        }

    @classmethod
    def from_checkpoint(cls, data):
        """Rebuild a session from to_checkpoint() output. Rejects tampering."""
        state, request_count, max_turns, max_attempts = _restore_checkpoint(data)
        restored = cls.__new__(cls)
        restored.__state = state
        restored.__request_count = request_count
        restored.__max_turns = max_turns
        restored.__max_completion_attempts = max_attempts
        return restored

    def execute(self, action: str, arguments: dict) -> ActionResult:
        state = self.__state
        if state.status in {S.COMPLETED, S.PAUSED, S.AWAITING_VERIFICATION, S.INCONCLUSIVE}:
            if action != "reopen_investigation" or state.status not in {S.COMPLETED, S.INCONCLUSIVE}:
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
                    and self.__state.status not in {S.COMPLETED, S.PAUSED, S.INCONCLUSIVE}):
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
        if action == "declare_inconclusive":
            return self.__declare_inconclusive(args)
        if action == "reopen_investigation":
            return self.__reopen(args)
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

    def __declare_inconclusive(self, args):
        state = self.__state
        report = InconclusiveReport(**args)
        verify_inconclusive(state, report)
        self.__state = replace(state, status=S.INCONCLUSIVE, inconclusive=report)
        return ActionResult(self.__state)

    def __reopen(self, _args):
        # Trusted technician path only: the model tool allowlist never exposes
        # this action. Prior recommendation/report records stay intact as audit.
        state = self.__state
        if state.status not in {S.COMPLETED, S.INCONCLUSIVE}:
            raise Rejected(f"Cannot reopen a session that is {state.status}")
        self.__state = replace(state, status=S.INVESTIGATING)
        return ActionResult(self.__state)

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


def _recommendation_dict(candidate):
    if candidate is None:
        return None
    return {
        "hypothesis_id": candidate.hypothesis_id, "action": candidate.action,
        "evidence_ids": list(candidate.evidence_ids),
        "acknowledged_contradictions": list(candidate.acknowledged_contradictions),
    }


def _restore_checkpoint(data):
    """Validate checkpoint data and rebuild (state, request_count, limits)."""
    if not isinstance(data, dict):
        raise Rejected("Checkpoint must be an object")
    if data.get("version") != CHECKPOINT_VERSION:
        raise Rejected("Unsupported checkpoint version")
    sid, problem = data.get("id"), data.get("problem")
    if not is_text(sid) or not is_text(problem):
        raise Rejected("Checkpoint session identity is invalid")
    try:
        status = S(data.get("status"))
    except ValueError:
        raise Rejected("Checkpoint status is invalid") from None
    if status is S.AWAITING_VERIFICATION:
        raise Rejected("Checkpoint status is invalid")
    for key in ("turn_count", "completion_attempts", "request_count"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise Rejected(f"Checkpoint {key} is invalid")
    for key in ("max_turns", "max_completion_attempts"):
        if type(data.get(key)) is not int or data[key] < 1:
            raise Rejected(f"Checkpoint {key} is invalid")
    prefix = f"{sid}:"
    evidence = _restore_evidence(data.get("evidence"), prefix)
    by_id = {item.id: item for item in evidence}
    hypotheses = _restore_hypotheses(data.get("hypotheses"), prefix, by_id)
    hypothesis_ids = {item.id for item in hypotheses}
    next_action = _restore_request(data.get("next_action"), prefix)
    recommendation = _restore_recommendation(
        data.get("recommendation"), by_id, hypothesis_ids)
    verifications = _restore_verifications(
        data.get("verifications"), by_id, hypothesis_ids)
    inconclusive = _restore_inconclusive(data.get("inconclusive"), by_id)
    pause_reason = data.get("pause_reason")
    if pause_reason is not None and not is_text(pause_reason):
        raise Rejected("Checkpoint pause reason is invalid")
    if (status is S.NEEDS_INPUT) != (next_action is not None):
        raise Rejected("Checkpoint request state does not match its status")
    if status is S.COMPLETED and (
            recommendation is None or not verifications
            or not verifications[-1].passed
            or verifications[-1].candidate != recommendation):
        raise Rejected("Checkpoint completion record is inconsistent")
    if status is S.INCONCLUSIVE and inconclusive is None:
        raise Rejected("Checkpoint inconclusive record is missing")
    if (status is S.PAUSED) != (pause_reason is not None):
        raise Rejected("Checkpoint pause record does not match its status")
    if data["completion_attempts"] != len(verifications):
        raise Rejected("Checkpoint completion count is inconsistent")
    if data["turn_count"] < len(evidence):
        raise Rejected("Checkpoint turn count is inconsistent")
    if data["request_count"] < _max_request_number(next_action, evidence, prefix):
        raise Rejected("Checkpoint request counter regressed")
    state = Session(
        id=sid, problem=problem, status=status, turn_count=data["turn_count"],
        completion_attempts=data["completion_attempts"], evidence=evidence,
        hypotheses=hypotheses, next_action=next_action,
        recommendation=recommendation, verifications=verifications,
        inconclusive=inconclusive, pause_reason=pause_reason,
    )
    if recommendation is not None:
        try:
            verify_recommendation(state, recommendation)
        except Rejected as exc:
            raise Rejected(f"Checkpoint recommendation is invalid: {exc}") from None
    if inconclusive is not None:
        try:
            verify_inconclusive(state, inconclusive)
        except Rejected as exc:
            raise Rejected(f"Checkpoint inconclusive report is invalid: {exc}") from None
    return state, data["request_count"], data["max_turns"], data["max_completion_attempts"]


def _restore_evidence(items, prefix):
    if not isinstance(items, list):
        raise Rejected("Checkpoint evidence is invalid")
    restored = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise Rejected("Checkpoint evidence is invalid")
        eid = item.get("id")
        if not is_text(eid) or not eid.startswith(prefix):
            raise Rejected("Checkpoint evidence id is invalid")
        if not is_text(item.get("source")) or not is_text(item.get("statement")):
            raise Rejected("Checkpoint evidence text is invalid")
        provenance = item.get("provenance")
        if (not isinstance(provenance, list) or not provenance
                or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                       or not is_text(pair[0]) or not is_text(pair[1])
                       for pair in provenance)):
            raise Rejected("Checkpoint provenance is invalid")
        if type(item.get("order")) is not int or item["order"] != position:
            raise Rejected("Checkpoint evidence order is invalid")
        request_id = item.get("request_id")
        if (request_id is not None
                and (not is_text(request_id) or not request_id.startswith(prefix))):
            raise Rejected("Checkpoint evidence link is invalid")
        restored.append(Evidence(
            eid, item["source"], item["statement"],
            tuple((key, value) for key, value in provenance),
            position, request_id,
        ))
    if len({item.id for item in restored}) != len(restored):
        raise Rejected("Checkpoint evidence ids repeat")
    return tuple(restored)


def _restore_hypotheses(items, prefix, by_id):
    if not isinstance(items, list):
        raise Rejected("Checkpoint hypotheses are invalid")
    restored = []
    for item in items:
        if not isinstance(item, dict):
            raise Rejected("Checkpoint hypotheses are invalid")
        hid = item.get("id")
        if not is_text(hid) or not hid.startswith(prefix):
            raise Rejected("Checkpoint hypothesis id is invalid")
        if not is_text(item.get("cause")) or not is_text(item.get("rationale")):
            raise Rejected("Checkpoint hypothesis text is invalid")
        try:
            status = H(item.get("status"))
        except ValueError:
            raise Rejected("Checkpoint hypothesis status is invalid") from None
        supporting = _restore_refs(item.get("supporting"), by_id, "hypothesis support")
        contradicting = _restore_refs(
            item.get("contradicting"), by_id, "hypothesis contradiction")
        if set(supporting) & set(contradicting):
            raise Rejected("Checkpoint hypothesis refs overlap")
        resolutions = item.get("resolutions")
        if (not isinstance(resolutions, list)
                or any(not isinstance(pair, (list, tuple)) or len(pair) != 2
                       for pair in resolutions)):
            raise Rejected("Checkpoint resolutions are invalid")
        for contradiction, support in resolutions:
            if contradiction not in contradicting or support not in supporting:
                raise Rejected("Checkpoint resolution links are invalid")
            if by_id[support].order <= by_id[contradiction].order:
                raise Rejected("Checkpoint resolution order is invalid")
        eliminated_at = item.get("eliminated_at")
        if eliminated_at is not None and (
                type(eliminated_at) is not int or eliminated_at < 0):
            raise Rejected("Checkpoint elimination mark is invalid")
        restored.append(Hypothesis(
            hid, item["cause"], status, supporting, contradicting,
            tuple((old, new) for old, new in resolutions),
            item["rationale"], eliminated_at,
        ))
    if len({item.id for item in restored}) != len(restored):
        raise Rejected("Checkpoint hypothesis ids repeat")
    return tuple(restored)


def _restore_refs(refs, by_id, label):
    if not isinstance(refs, list) or any(not is_text(ref) for ref in refs):
        raise Rejected(f"Checkpoint {label} is invalid")
    if len(set(refs)) != len(refs) or any(ref not in by_id for ref in refs):
        raise Rejected(f"Checkpoint {label} is invalid")
    return tuple(refs)


def _restore_request(value, prefix):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise Rejected("Checkpoint pending request is invalid")
    rid = value.get("id")
    if not is_text(rid) or not rid.startswith(prefix):
        raise Rejected("Checkpoint request id is invalid")
    if value.get("kind") not in {"request_diagnostic_test", "request_user_evidence"}:
        raise Rejected("Checkpoint request kind is invalid")
    if not is_text(value.get("action")):
        raise Rejected("Checkpoint request text is invalid")
    observations = value.get("observations")
    if (not isinstance(observations, list) or not observations
            or any(not is_text(item) for item in observations)
            or len(set(observations)) != len(observations)):
        raise Rejected("Checkpoint request questions are invalid")
    return InputRequest(rid, value["kind"], value["action"], tuple(observations))


def _restore_recommendation(value, by_id, hypothesis_ids):
    if value is None:
        return None
    if not isinstance(value, dict) or not is_text(value.get("action")):
        raise Rejected("Checkpoint recommendation is invalid")
    if value.get("hypothesis_id") not in hypothesis_ids:
        raise Rejected("Checkpoint recommendation is invalid")
    evidence_ids = _restore_refs(
        value.get("evidence_ids"), by_id, "recommendation evidence")
    if not evidence_ids:
        raise Rejected("Checkpoint recommendation is invalid")
    acknowledged = _restore_refs(
        value.get("acknowledged_contradictions"), by_id,
        "recommendation contradictions")
    return Recommendation(
        value["hypothesis_id"], value["action"], evidence_ids, acknowledged)


def _restore_verifications(items, by_id, hypothesis_ids):
    if not isinstance(items, list):
        raise Rejected("Checkpoint verifications are invalid")
    restored = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise Rejected("Checkpoint verifications are invalid")
        if type(item.get("attempt")) is not int or item["attempt"] != position:
            raise Rejected("Checkpoint verification order is invalid")
        if type(item.get("passed")) is not bool:
            raise Rejected("Checkpoint verification verdict is invalid")
        issues = item.get("issues")
        if (not isinstance(issues, list)
                or any(not isinstance(text, str) for text in issues)):
            raise Rejected("Checkpoint verification issues are invalid")
        if item["passed"] != (not issues):
            raise Rejected("Checkpoint verification verdict is invalid")
        candidate = item.get("candidate")
        if candidate is not None and (
                not isinstance(candidate, dict)
                or not is_text(candidate.get("hypothesis_id"))
                or not is_text(candidate.get("action"))
                or not isinstance(candidate.get("evidence_ids"), list)
                or not isinstance(candidate.get("acknowledged_contradictions"), list)
                or any(not is_text(ref) for ref in
                       candidate["evidence_ids"] + candidate["acknowledged_contradictions"])):
            raise Rejected("Checkpoint verification candidate is invalid")
        if item["passed"] and candidate is None:
            raise Rejected("Checkpoint verification candidate is invalid")
        restored.append(Verification(
            position, item["passed"], tuple(issues),
            None if candidate is None else Recommendation(
                candidate["hypothesis_id"], candidate["action"],
                tuple(candidate["evidence_ids"]),
                tuple(candidate["acknowledged_contradictions"])),
        ))
    return tuple(restored)


def _restore_inconclusive(value, by_id):
    if value is None:
        return None
    if (not isinstance(value, dict) or not is_text(value.get("summary"))
            or not is_text(value.get("remaining_possibilities"))
            or not is_text(value.get("safe_next_steps"))):
        raise Rejected("Checkpoint inconclusive report is invalid")
    checked = _restore_refs(
        value.get("checked_evidence_ids"), by_id, "inconclusive evidence")
    if not checked:
        raise Rejected("Checkpoint inconclusive report is invalid")
    return InconclusiveReport(
        value["summary"], checked, value["remaining_possibilities"],
        value["safe_next_steps"])


def _max_request_number(next_action, evidence, prefix):
    marker = f"{prefix}request"
    ids = [next_action.id] if next_action is not None else []
    ids += [item.request_id for item in evidence if item.request_id is not None]
    highest = 0
    for rid in ids:
        if rid.startswith(marker) and rid[len(marker):].isdigit():
            highest = max(highest, int(rid[len(marker):]))
    return highest
