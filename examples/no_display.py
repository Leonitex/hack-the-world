"""Scripted fixture illustrating the core, not a model or troubleshooting tree.

Run from the repository root: python -m examples.no_display
"""

from diagnostic_core import DiagnosticSession


def run():
    core = DiagnosticSession("Computer powers on and fans spin, but there is no display.")
    core.execute("record_evidence", {
        "source": "user_text", "statement": core.snapshot.problem,
        "provenance": {"reported_by": "fixture-user"},
    })
    hypotheses = {
        cause: core.execute("propose_hypothesis", {"cause": cause}).record_id
        for cause in ("Display cable", "Monitor input", "RAM connection", "GPU connection")
    }
    request = core.execute("request_diagnostic_test", {
        "action": "Try a known-good display cable.",
        "observations": ["Does the display appear?"],
    })
    print("Handoff:", request.session.status)
    result = core.execute("record_test_result", {
        "request_id": request.record_id,
        "statement": "Display appears with the replacement cable; failure returns with the original cable.",
        "provenance": {"performed_by": "fixture-user", "method": "repeatable cable comparison"},
    })
    print("After result:", result.session.status)
    core.execute("update_hypothesis", {
        "hypothesis_id": hypotheses["Display cable"], "status": "confirmed",
        "supporting": [result.record_id], "contradicting": [], "resolutions": {},
        "rationale": "The observed failure follows the original cable in the repeated comparison.",
    })
    for cause in ("Monitor input", "RAM connection", "GPU connection"):
        core.execute("update_hypothesis", {
            "hypothesis_id": hypotheses[cause], "status": "weakened",
            "supporting": [], "contradicting": [result.record_id], "resolutions": {},
            "rationale": "The display works after changing only the cable; this alternative is less supported.",
        })
    completed = core.execute("submit_recommendation", {
        "hypothesis_id": hypotheses["Display cable"], "action": "Replace the failing display cable.",
        "evidence_ids": [result.record_id], "acknowledged_contradictions": [],
    })
    print("Verification passed:", completed.verification.passed)
    print("Session:", completed.session.status)
    for hypothesis in completed.session.hypotheses:
        print(f"  {hypothesis.cause}: {hypothesis.status}")
    print("Recommendation:", completed.session.recommendation.action)
    return completed


if __name__ == "__main__":
    run()
