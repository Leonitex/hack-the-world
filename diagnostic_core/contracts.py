"""Small action vocabulary. No action accepts replacement session state.

Fields map to simple validators. Future provider adapters must enumerate only
MODEL_ACTION_FIELDS when exposing model tools, never the combined ACTION_FIELDS.
Evidence-writing actions must be dispatched by trusted application code using
the actual user/tool result, never a model's invented observation.
"""

from .models import Rejected


MODEL_ACTION_FIELDS = {
    "propose_hypothesis": {"cause": "text"},
    "update_hypothesis": {
        "hypothesis_id": "text", "status": "text", "supporting": "refs",
        "contradicting": "refs", "resolutions": "resolutions", "rationale": "text",
    },
    "request_diagnostic_test": {"action": "text", "observations": "observations"},
    "request_user_evidence": {"action": "text", "observations": "observations"},
    "submit_recommendation": {
        "hypothesis_id": "text", "action": "text", "evidence_ids": "refs",
        "acknowledged_contradictions": "refs",
    },
}

TRUSTED_INGESTION_ACTION_FIELDS = {
    "record_evidence": {"source": "text", "statement": "text", "provenance": "metadata"},
    "record_test_result": {
        "request_id": "text", "statement": "text", "provenance": "metadata",
    },
    "provide_user_evidence": {
        "request_id": "text", "source": "text", "statement": "text", "provenance": "metadata",
    },
}

if MODEL_ACTION_FIELDS.keys() & TRUSTED_INGESTION_ACTION_FIELDS.keys():
    raise ValueError("Actions must belong to exactly one exposure class")

# The application API validates both classes; model tool enumeration uses only
# MODEL_ACTION_FIELDS. Derivation ensures no action is left unclassified.
ACTION_FIELDS = {**MODEL_ACTION_FIELDS, **TRUSTED_INGESTION_ACTION_FIELDS}


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_arguments(action, arguments):
    if not isinstance(action, str) or action not in ACTION_FIELDS:
        raise Rejected("Unknown action")
    fields = ACTION_FIELDS[action]
    if not isinstance(arguments, dict) or set(arguments) != set(fields):
        raise Rejected(f"Expected exactly these fields: {', '.join(fields)}")
    normalized = {}
    for name, kind in fields.items():
        value = arguments[name]
        if kind == "text":
            valid = is_text(value)
        elif kind in {"metadata", "resolutions"}:
            valid = (isinstance(value, dict) and (bool(value) or kind == "resolutions")
                     and all(is_text(k) and is_text(v) for k, v in value.items()))
            if valid:
                value = tuple(sorted(value.items()))
        else:
            valid = (isinstance(value, (list, tuple))
                     and all(is_text(item) for item in value)
                     and len(set(value)) == len(value))
            if valid:
                value = tuple(value)
                valid = kind != "observations" or bool(value)
        if not valid:
            raise Rejected(f"Invalid {name}: expected {kind}")
        normalized[name] = value
    return normalized
