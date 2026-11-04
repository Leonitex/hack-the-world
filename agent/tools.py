"""Model-selectable tool definitions and structural validation.

Tool names derive from MODEL_ACTION_FIELDS; there is no second handwritten
list of model action names. Trusted ingestion actions are never exposed
here. Anything malformed raises StructuralError before the diagnostic core
is contacted, so structural failures never consume a core turn.
"""

from diagnostic_core.contracts import (
    MODEL_ACTION_FIELDS, TRUSTED_INGESTION_ACTION_FIELDS, validate_arguments,
)
from diagnostic_core.models import HypothesisStatus, Rejected


class StructuralError(ValueError):
    """Malformed provider output; the diagnostic core was not contacted."""


HYPOTHESIS_STATUS_VALUES = tuple(status.value for status in HypothesisStatus)

TOOL_DESCRIPTIONS = {
    "propose_hypothesis": "Propose a new candidate cause as a possible hypothesis.",
    "update_hypothesis": (
        "Reassess an existing hypothesis. Support and confirmation require "
        "supporting evidence IDs; weakening and elimination require "
        "contradicting evidence IDs."
    ),
    "request_diagnostic_test": (
        "Ask the user to perform a concrete diagnostic test and report what "
        "happened. The loop pauses until trusted code records the real result."
    ),
    "request_user_evidence": (
        "Ask the user to supply a concrete observation. The loop pauses until "
        "trusted code records the real observation."
    ),
    "submit_recommendation": (
        "Attempt completion with a recommended action grounded in cited "
        "session evidence. Mandatory verification runs synchronously."
    ),
}

FIELD_DESCRIPTIONS = {
    ("propose_hypothesis", "cause"): "Candidate cause being proposed.",
    ("update_hypothesis", "hypothesis_id"): "ID of an existing hypothesis in this session.",
    ("update_hypothesis", "status"): "New assessment for the hypothesis.",
    ("update_hypothesis", "supporting"): "Evidence IDs supporting this assessment.",
    ("update_hypothesis", "contradicting"): "Evidence IDs contradicting the hypothesis.",
    ("update_hypothesis", "resolutions"): (
        "Map of a contradicting evidence ID to a later supporting evidence ID that resolves it."
    ),
    ("update_hypothesis", "rationale"): "Reason for the assessment, referencing observed evidence.",
    ("request_diagnostic_test", "action"): "Concrete test for the user to perform.",
    ("request_diagnostic_test", "observations"): "Distinct questions the reported result must answer.",
    ("request_user_evidence", "action"): "Concrete observation for the user to supply.",
    ("request_user_evidence", "observations"): "Distinct questions the supplied observation must answer.",
    ("submit_recommendation", "hypothesis_id"): "ID of the supported or confirmed hypothesis.",
    ("submit_recommendation", "action"): "Recommended action, grounded in the cited evidence.",
    ("submit_recommendation", "evidence_ids"): "Session evidence IDs supporting the recommendation.",
    ("submit_recommendation", "acknowledged_contradictions"): (
        "Unresolved contradicting evidence IDs being surfaced, not hidden."
    ),
}

_KIND_DESCRIPTIONS = {
    "text": "Non-blank text.",
    "refs": "List of distinct ID strings.",
    "observations": "Non-empty list of distinct question strings.",
    "resolutions": "Map of ID strings to ID strings.",
}


def _schema_for(action, field, kind):
    if kind == "text":
        schema = {"type": "string", "minLength": 1}
        if action == "update_hypothesis" and field == "status":
            schema["enum"] = list(HYPOTHESIS_STATUS_VALUES)
        return schema
    if kind == "refs":
        return {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}
    if kind == "observations":
        return {
            "type": "array", "items": {"type": "string", "minLength": 1},
            "uniqueItems": True, "minItems": 1,
        }
    if kind == "resolutions":
        return {
            "type": "object",
            "propertyNames": {"type": "string", "minLength": 1},
            "additionalProperties": {"type": "string", "minLength": 1},
        }
    raise AssertionError(f"Unknown contract field kind: {kind!r}")


def _build_tools():
    tools = []
    for action, fields in MODEL_ACTION_FIELDS.items():
        properties = {}
        for field, kind in fields.items():
            schema = _schema_for(action, field, kind)
            schema["description"] = FIELD_DESCRIPTIONS.get(
                (action, field), _KIND_DESCRIPTIONS[kind],
            )
            properties[field] = schema
        tools.append({
            "name": action,
            "description": TOOL_DESCRIPTIONS.get(action, f"Perform the {action} diagnostic action."),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(fields),
                "additionalProperties": False,
            },
        })
    return tuple(tools)


MODEL_TOOLS = _build_tools()


def validate_tool_call(name, arguments):
    """Reject anything but a well-shaped model-selectable call.

    Trusted ingestion names are refused explicitly. Shape enforcement reuses
    the core contract validator so the two cannot drift, with failures
    translated to StructuralError to prove the core was not contacted.
    """
    if isinstance(name, str) and name in TRUSTED_INGESTION_ACTION_FIELDS:
        raise StructuralError(f"{name!r} is a trusted ingestion action and is never model-callable")
    if not isinstance(name, str) or name not in MODEL_ACTION_FIELDS:
        raise StructuralError(f"Unknown model tool: {name!r}")
    if not isinstance(arguments, dict):
        raise StructuralError(f"Invalid arguments for {name!r}: expected an object")
    try:
        validate_arguments(name, arguments)
    except Rejected as exc:
        raise StructuralError(str(exc)) from exc
    if name == "update_hypothesis" and arguments["status"] not in HYPOTHESIS_STATUS_VALUES:
        raise StructuralError(
            f"Invalid status: expected one of {', '.join(HYPOTHESIS_STATUS_VALUES)}",
        )
