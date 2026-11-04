"""Meta Model API provider adapter (Muse Spark native tool calling).

Each decide() call is one stateless Chat Completions request built from the
authoritative diagnostic snapshot plus recent feedback: a developer
instruction, a rendered state message, and the model-selectable tools in
the OpenAI-compatible function format. No conversation is continued
across steps, so no assistant/tool-call IDs are tracked and a restart
loses nothing: everything the model needs is re-rendered from
DiagnosticSession state. The model never sees hidden provider memory
because there is none.

Configuration (constructor argument wins, then environment, then default):
MODEL_API_KEY (fallback: META_MODEL_API_KEY), META_MODEL_ID (default
muse-spark-1.3), META_BASE_URL (default https://api.meta.ai/v1). The key
is passed only to the SDK client constructor and never logged, rendered,
returned, or embedded in requests.

Meta supports only tool_choice "auto", so a reply may carry zero calls
(plain text) or, despite parallel_tool_calls=False, several. Zero calls
become an empty decision and multiple calls pass through untouched; both
reach the loop's existing structural handling and none execute except
through the normal single-call path. Any accompanying plain-text content
is dropped, never surfaced. API and response-integrity failures become ProviderError. HTTP status errors
surface only the status code plus the Meta message/type/param/code fields;
headers, request metadata, and full bodies never surface. The adapter never
touches DiagnosticSession.
"""

import json
import os

from .providers import Provider, ProviderDecision, ProviderError, ToolCall

DEFAULT_MODEL_ID = "muse-spark-1.3"
DEFAULT_BASE_URL = "https://api.meta.ai/v1"

try:
    from openai import (
        APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
        BadRequestError, NotFoundError, OpenAI, OpenAIError, RateLimitError,
    )
except ImportError:
    OpenAI = None

    class OpenAIError(Exception):
        """Placeholder used only when the openai package is not installed."""

    class APIStatusError(OpenAIError):
        pass

    class AuthenticationError(APIStatusError):
        pass

    class BadRequestError(APIStatusError):
        pass

    class NotFoundError(APIStatusError):
        pass

    class RateLimitError(APIStatusError):
        pass

    class APIConnectionError(OpenAIError):
        pass

    class APITimeoutError(APIConnectionError):
        pass


DEVELOPER_INSTRUCTION = (
    "You are an evidence-driven diagnostic agent. Investigate the problem by "
    "gathering evidence and testing competing explanations. "
    "Maintain uncertainty: keep multiple plausible hypotheses until evidence "
    "weakens or eliminates them. "
    "On each step respond with exactly one tool call, never plain text. "
    "Use only the supplied tools with exact arguments. "
    "Never invent test results or observations. Evidence and results in the "
    "state below are authoritative application records. "
    "When evidence is insufficient, request a concrete user test or "
    "observation instead of guessing. "
    "Never claim certainty beyond what the cited evidence supports. "
    "Submit a recommendation only when a hypothesis is sufficiently "
    "supported by cited session evidence."
)


def to_openai_tool(tool):
    """Map one MODEL_TOOLS entry to the OpenAI-compatible function format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        },
    }


def render_state(request):
    """Render a bounded, deterministic, model-facing state summary.

    Evidence and hypotheses are bounded by the core turn budget; feedback
    arrives pre-windowed by the loop. Only plain values and stable IDs are
    exposed, never Python internals.
    """
    session = request.session
    lines = [
        f"Problem: {session.problem}",
        f"Session status: {session.status} (turn {request.turn_count}, "
        f"completion attempts {request.completion_attempts}, "
        f"{request.remaining_provider_steps} provider steps remaining)",
        "",
        "Evidence:",
    ]
    for item in session.evidence:
        lines.append(f"- [{item.id}] ({item.source}) {item.statement}")
    if not session.evidence:
        lines.append("- none recorded")
    lines += ["", "Hypotheses:"]
    for hypothesis in session.hypotheses:
        lines.append(
            f"- [{hypothesis.id}] {hypothesis.cause} ({hypothesis.status}) "
            f"supporting: {', '.join(hypothesis.supporting) or 'none'}; "
            f"contradicting: {', '.join(hypothesis.contradicting) or 'none'}"
        )
        if hypothesis.resolutions:
            resolved = ", ".join(f"{old} -> {new}" for old, new in hypothesis.resolutions)
            lines.append(f"  resolved: {resolved}")
        if hypothesis.rationale:
            lines.append(f"  rationale: {hypothesis.rationale}")
    if not session.hypotheses:
        lines.append("- none proposed")
    lines += ["", "Pending request:"]
    pending = session.next_action
    if pending is None:
        lines.append("- none")
    else:
        lines.append(f"- kind: {pending.kind}; action: {pending.action}")
        for question in pending.observations:
            lines.append(f"  - {question}")
    lines += ["", "Recent feedback:"]
    for entry in request.feedback:
        lines.append(_render_feedback(entry))
    if not request.feedback:
        lines.append("- none yet")
    return "\n".join(lines)


def _render_feedback(entry):
    outcome = "ok" if entry.ok else "failed"
    text = f"- {entry.tool or 'provider'}: {outcome}: {entry.message}"
    if entry.record_id is not None:
        text += f" [record {entry.record_id}]"
    if entry.verification_passed is not None:
        verdict = "passed" if entry.verification_passed else "failed"
        text += f" [verification {verdict}"
        if entry.verification_issues:
            text += f": {'; '.join(entry.verification_issues)}"
        text += "]"
    return text


def _error_text(fields, name):
    value = fields.get(name)
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _status_details(exc):
    """Extract safe structured fields from an SDK status error.

    Returns (status, message, type, param, code); absent fields are None.
    Only these explicit fields are read: the status code plus the Meta
    error envelope. Headers, request metadata, and full bodies are never
    included, and the exception itself is never stringified here.
    """
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = None
    message = error_type = param = code = None
    body = getattr(exc, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        message = body
    elif isinstance(body, dict):
        error = body.get("error")
        fields = error if isinstance(error, dict) else body
        message = _error_text(fields, "message")
        error_type = _error_text(fields, "type")
        param = _error_text(fields, "param")
        code = _error_text(fields, "code")
    return status, message, error_type, param, code


def _format_status_error(verb, exc):
    status, message, error_type, param, code = _status_details(exc)
    label = " ".join(
        part for part in (str(status) if status is not None else None, error_type) if part
    )
    qualifiers = ", ".join(
        part for part in (
            f"param={param}" if param else None,
            f"code={code}" if code else None,
        ) if part
    )
    if qualifiers:
        label = f"{label}, {qualifiers}" if label else qualifiers
    text = f"Meta API {verb}"
    if label:
        text += f" ({label})"
    if message:
        text += f": {message}"
    return text


class MetaProvider(Provider):
    """Translate between ProviderRequest and Meta Chat Completions calls.

    Pass client=... (anything exposing chat.completions.create) to run
    without the openai package or network access; used by tests.
    """

    def __init__(self, *, api_key=None, model=None, base_url=None, client=None, timeout=None,
                 image_data_url=None):
        self._model = model or os.environ.get("META_MODEL_ID") or DEFAULT_MODEL_ID
        self._base_url = base_url or os.environ.get("META_BASE_URL") or DEFAULT_BASE_URL
        self._image_data_url = image_data_url
        if client is None:
            if OpenAI is None:
                raise ProviderError(
                    "The openai package is required for live Meta API calls "
                    "(pip install -r requirements.txt)."
                )
            key = api_key or os.environ.get("MODEL_API_KEY") or os.environ.get("META_MODEL_API_KEY")
            if not key or not key.strip():
                raise ProviderError(
                    "Missing Meta API key: set MODEL_API_KEY in the environment "
                    "or pass api_key=.... No request was sent."
                )
            client_kwargs = {"api_key": key, "base_url": self._base_url}
            if timeout is not None:
                client_kwargs["timeout"] = timeout
            self._client = OpenAI(**client_kwargs)
        else:
            self._client = client

    @property
    def model(self):
        return self._model

    @property
    def base_url(self):
        return self._base_url

    def set_image(self, image_data_url):
        """Attach or replace the photo the model sees on later decisions."""
        self._image_data_url = image_data_url

    def decide(self, request):
        tools = [to_openai_tool(tool) for tool in request.tools]
        messages = [
            {"role": "developer", "content": DEVELOPER_INSTRUCTION},
            {"role": "user", "content": self._user_content(request)},
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
            )
        except AuthenticationError as exc:
            raise ProviderError(
                "Meta API authentication failed: verify MODEL_API_KEY."
            ) from exc
        except RateLimitError as exc:
            raise ProviderError("Meta API rate limit exceeded.") from exc
        except NotFoundError as exc:
            raise ProviderError(
                f"Meta API resource not found: check model {self._model!r} "
                f"and base URL {self._base_url!r}."
            ) from exc
        except BadRequestError as exc:
            raise ProviderError(_format_status_error("rejected request", exc)) from exc
        except APITimeoutError as exc:
            raise ProviderError("Meta API request timed out.") from exc
        except APIConnectionError as exc:
            raise ProviderError("Meta API network failure.") from exc
        except APIStatusError as exc:
            status = _status_details(exc)[0]
            if isinstance(status, int) and 500 <= status <= 599:
                raise ProviderError(_format_status_error("server failure", exc)) from exc
            raise ProviderError(_format_status_error("request failed", exc)) from exc
        except OpenAIError as exc:
            raise ProviderError("Meta API failure.") from exc
        return self._translate(response)

    def _user_content(self, request):
        state_text = render_state(request)
        if not self._image_data_url:
            return state_text
        return [
            {"type": "text", "text": state_text},
            {"type": "image_url", "image_url": {"url": self._image_data_url, "detail": "auto"}},
        ]

    @staticmethod
    def _translate(response):
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ProviderError("Malformed Meta response: no completion choices.")
        message = getattr(choices[0], "message", None)
        if message is None:
            raise ProviderError("Malformed Meta response: missing message.")
        calls = []
        for call in list(getattr(message, "tool_calls", None) or []):
            function = getattr(call, "function", None)
            name = getattr(function, "name", None)
            raw = getattr(function, "arguments", None)
            if not isinstance(name, str) or not isinstance(raw, str):
                raise ProviderError("Malformed Meta response: invalid tool call shape.")
            try:
                arguments = json.loads(raw)
            except ValueError as exc:
                raise ProviderError(
                    f"Malformed Meta response: tool arguments are not valid JSON: {exc}"
                )
            if not isinstance(arguments, dict):
                raise ProviderError(
                    "Malformed Meta response: tool arguments must decode to an object."
                )
            calls.append(ToolCall(name, arguments))
        return ProviderDecision(tuple(calls))
