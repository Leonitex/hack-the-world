"""Provider-neutral model interface. Providers choose; they never execute.

A provider receives a read-only request (immutable session snapshot, the
model-selectable tool definitions, bounded recent feedback, and observed
budgets) and returns exactly one tool call per decision. Providers never
receive the live DiagnosticSession, so they cannot mutate authoritative
diagnostic state directly.
"""

from dataclasses import dataclass


class ProviderError(Exception):
    """The provider failed to return a usable decision."""


@dataclass(frozen=True)
class ToolCall:
    """One model-requested tool invocation. Shape is validated by the loop."""

    name: str
    arguments: dict


@dataclass(frozen=True)
class ProviderDecision:
    """Exactly one tool call is required; the loop rejects anything else."""

    calls: tuple = ()


@dataclass(frozen=True)
class StepFeedback:
    """Outcome of one loop step, reported back to the provider."""

    tool: str | None
    ok: bool
    message: str
    record_id: str | None = None
    verification_passed: bool | None = None
    verification_issues: tuple = ()


@dataclass(frozen=True)
class ProviderRequest:
    """Everything a provider may use to choose the next tool call."""

    problem: str
    session: object
    tools: tuple
    feedback: tuple
    turn_count: int
    completion_attempts: int
    remaining_provider_steps: int


class Provider:
    """Synchronous provider contract for current fakes and future adapters."""

    def decide(self, request: ProviderRequest) -> ProviderDecision:
        raise NotImplementedError


class FakeProvider(Provider):
    """Deterministic scripted provider for tests. No IO, no network.

    Each script entry is consumed by one decide() call and may be a ToolCall
    (wrapped in a single-call decision), a ProviderDecision, a list/tuple of
    calls (for zero/multiple-call shapes), a raw malformed payload returned
    as-is, an exception instance to raise, or a callable taking the request
    and returning any of the above.
    """

    def __init__(self, script):
        self._script = list(script)
        self.requests = []

    @property
    def decide_calls(self):
        return len(self.requests)

    def decide(self, request: ProviderRequest) -> ProviderDecision:
        self.requests.append(request)
        if not self._script:
            raise ProviderError("FakeProvider script exhausted")
        entry = self._script.pop(0)
        if isinstance(entry, BaseException):
            raise entry
        if callable(entry):
            entry = entry(request)
            if isinstance(entry, BaseException):
                raise entry
        if isinstance(entry, ProviderDecision):
            return entry
        if isinstance(entry, ToolCall):
            return ProviderDecision((entry,))
        if isinstance(entry, (list, tuple)):
            return ProviderDecision(tuple(entry))
        return entry
