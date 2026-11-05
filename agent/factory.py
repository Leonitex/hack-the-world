"""Demo provider selection. Baseten is the proven default route.

HTW_PROVIDER controls the choice: "meta" or "baseten" select explicitly,
"auto" (default) prefers the proven Baseten route when BASETEN_API_KEY is
present and falls back to Meta Model API when only MODEL_API_KEY (or the
legacy META_MODEL_API_KEY) is present. Only key presence is inspected
here; key values stay with the providers that read them.

HTW_E2E_FAKE_PROVIDER=1 overrides every choice above with a deterministic
scripted FakeProvider for browser E2E. It makes no network calls and needs
no keys. Any other value (including unset) leaves normal selection alone.
Never enable it for a real diagnosis.

The fixture serves a fixed multi-turn script by default. A problem
statement containing "e2e-repeat" selects the repeat-guard script
instead, in which the scripted model asks the same test twice so the
browser gate can prove the duplicate is blocked and a distinct follow-up
is presented.
"""

import os

from .baseten import BasetenMuseProvider
from .meta_provider import MetaProvider
from .providers import FakeProvider, ProviderError, ToolCall

CHOICE_ENV_VAR = "HTW_PROVIDER"
E2E_ENV_VAR = "HTW_E2E_FAKE_PROVIDER"
E2E_REPEAT_MARKER = "e2e-repeat"


def e2e_script():
    """Fixed scripted decisions driving the multi-turn browser E2E flows."""
    return [
        ToolCall("propose_hypothesis", {"cause": "E2E Cause A"}),
        ToolCall("propose_hypothesis", {"cause": "E2E Cause B"}),
        ToolCall("request_user_evidence", {
            "action": "E2E check one: report the indicator light.",
            "observations": ["E2E observation one."],
        }),
        ToolCall("propose_hypothesis", {"cause": "E2E Cause C"}),
        ToolCall("request_user_evidence", {
            "action": "E2E check two: report the startup sound.",
            "observations": ["E2E observation two."],
        }),
        ToolCall("propose_hypothesis", {"cause": "E2E Cause D"}),
        ToolCall("request_user_evidence", {
            "action": "E2E check three: report the charging port.",
            "observations": ["E2E observation three."],
        }),
    ]


def e2e_repeat_script():
    """Repeat-guard script: the model re-asks an answered test verbatim."""
    return [
        ToolCall("propose_hypothesis", {"cause": "E2E Cause A"}),
        ToolCall("request_user_evidence", {
            "action": "E2E repeat check: report the indicator light.",
            "observations": ["E2E repeat observation."],
        }),
        ToolCall("request_user_evidence", {
            "action": "E2E repeat check: report the indicator light.",
            "observations": ["E2E repeat observation."],
        }),
        ToolCall("request_user_evidence", {
            "action": "E2E distinct follow-up: report the startup sound.",
            "observations": ["E2E distinct observation."],
        }),
    ]


class E2EFakeProvider(FakeProvider):
    """Fixture provider selecting its fixed script from the problem text."""

    def __init__(self):
        super().__init__([])
        self._primed = False

    def decide(self, request):
        if not self._primed:
            self._primed = True
            problem = getattr(request, "problem", "") or ""
            if E2E_REPEAT_MARKER in problem.lower():
                self._script.extend(e2e_repeat_script())
            else:
                self._script.extend(e2e_script())
        return super().decide(request)


def _meta_key_present():
    return bool(os.environ.get("MODEL_API_KEY") or os.environ.get("META_MODEL_API_KEY"))


def create_provider(image_data_url=None):
    """Create (provider, ui_label) from HTW_PROVIDER and available keys."""
    if (os.environ.get(E2E_ENV_VAR) or "").strip() == "1":
        return E2EFakeProvider(), "Deterministic E2E fixture (fake, no network)"
    choice = (os.environ.get(CHOICE_ENV_VAR) or "auto").strip().lower()
    if choice == "meta":
        provider = MetaProvider(image_data_url=image_data_url)
    elif choice == "baseten":
        provider = BasetenMuseProvider(image_data_url=image_data_url)
    elif choice == "auto":
        if os.environ.get("BASETEN_API_KEY"):
            provider = BasetenMuseProvider(image_data_url=image_data_url)
        elif _meta_key_present():
            provider = MetaProvider(image_data_url=image_data_url)
        else:
            raise ProviderError(
                "No provider key found: set BASETEN_API_KEY or MODEL_API_KEY "
                "(HTW_PROVIDER=auto)."
            )
    else:
        raise ProviderError(f"Unknown HTW_PROVIDER={choice!r}: use auto, meta, or baseten.")
    if isinstance(provider, BasetenMuseProvider):
        label = "Meta Muse Spark Open via Baseten"
    else:
        label = f"Meta Model API ({provider.model})"
    return provider, label
