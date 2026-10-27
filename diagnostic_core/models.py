"""Immutable, provider-independent diagnostic records."""

from dataclasses import dataclass
from enum import StrEnum


class SessionStatus(StrEnum):
    INVESTIGATING = "investigating"
    NEEDS_INPUT = "needs_input"
    AWAITING_VERIFICATION = "awaiting_verification"
    COMPLETED = "completed"
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
    pause_reason: str | None = None


@dataclass(frozen=True)
class ActionResult:
    session: Session
    record_id: str | None = None
    verification: Verification | None = None


class Rejected(ValueError):
    """Invalid action; no evidence, hypothesis, or recommendation was committed."""
