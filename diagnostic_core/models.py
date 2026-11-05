"""Immutable, provider-independent diagnostic records."""

from dataclasses import dataclass
from enum import StrEnum


class SessionStatus(StrEnum):
    INVESTIGATING = "investigating"
    NEEDS_INPUT = "needs_input"
    AWAITING_VERIFICATION = "awaiting_verification"
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    PAUSED = "paused"


class HypothesisStatus(StrEnum):
    POSSIBLE = "possible"
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    ELIMINATED = "eliminated"
    CONFIRMED = "confirmed"


@dataclass(frozen=True)
class Evidence:
    id: str
    source: str
    statement: str
    provenance: tuple[tuple[str, str], ...]
    order: int
    request_id: str | None = None


@dataclass(frozen=True)
class Hypothesis:
    id: str
    cause: str
    status: HypothesisStatus = HypothesisStatus.POSSIBLE
    supporting: tuple[str, ...] = ()
    contradicting: tuple[str, ...] = ()
    resolutions: tuple[tuple[str, str], ...] = ()
    rationale: str = ""
    eliminated_at: int | None = None


@dataclass(frozen=True)
class InputRequest:
    id: str
    kind: str
    action: str
    observations: tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    hypothesis_id: str
    action: str
    evidence_ids: tuple[str, ...]
    # Contradictions must be explicitly surfaced, not silently omitted.
    acknowledged_contradictions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verification:
    attempt: int
    passed: bool
    issues: tuple[str, ...]
    candidate: Recommendation | None


@dataclass(frozen=True)
class InconclusiveReport:
    """Honest terminal handoff: what was checked, what remains, what is safe.

    Never a verified root cause. checked_evidence_ids must reference real
    session evidence; verification rejects invented citations.
    """

    summary: str
    checked_evidence_ids: tuple[str, ...]
    remaining_possibilities: str
    safe_next_steps: str


@dataclass(frozen=True)
class Session:
    id: str
    problem: str
    status: SessionStatus = SessionStatus.INVESTIGATING
    turn_count: int = 0
    completion_attempts: int = 0
    evidence: tuple[Evidence, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    next_action: InputRequest | None = None
    recommendation: Recommendation | None = None
    verifications: tuple[Verification, ...] = ()
    inconclusive: InconclusiveReport | None = None
    pause_reason: str | None = None


@dataclass(frozen=True)
class ActionResult:
    session: Session
    record_id: str | None = None
    verification: Verification | None = None


class Rejected(ValueError):
    """Invalid action; no evidence, hypothesis, or recommendation was committed."""
