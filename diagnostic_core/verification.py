"""Mandatory deterministic invariants; these are not selectable tools."""

from .models import HypothesisStatus as H, Rejected


TRANSITIONS = {
    H.POSSIBLE: {H.POSSIBLE, H.SUPPORTED, H.WEAKENED, H.ELIMINATED, H.CONFIRMED},
    H.SUPPORTED: {H.SUPPORTED, H.WEAKENED, H.ELIMINATED, H.CONFIRMED},
    H.WEAKENED: {H.WEAKENED, H.SUPPORTED, H.ELIMINATED, H.CONFIRMED},
    H.ELIMINATED: {H.ELIMINATED, H.SUPPORTED},
    H.CONFIRMED: {H.CONFIRMED, H.WEAKENED, H.ELIMINATED},
}


def verify_references(session, refs):
    known = {item.id for item in session.evidence}
    if any(ref not in known for ref in refs):
        raise Rejected("Evidence reference does not exist in this session")


def verify_hypothesis(session, old, new):
    verify_references(session, new.supporting + new.contradicting)
    if new.status not in TRANSITIONS[old.status]:
        raise Rejected(f"Invalid hypothesis transition: {old.status} -> {new.status}")
    if set(new.supporting) & set(new.contradicting):
        raise Rejected("Evidence cannot both support and contradict the same hypothesis")
    if new.status in {H.SUPPORTED, H.CONFIRMED} and not new.supporting:
        raise Rejected("Support or confirmation requires supporting evidence")
    if new.status in {H.WEAKENED, H.ELIMINATED} and not new.contradicting:
        raise Rejected("Weakening or elimination requires contradicting evidence")
    evidence = {e.id: e for e in session.evidence}
    for contradiction, support in new.resolutions:
        if contradiction not in new.contradicting or support not in new.supporting:
            raise Rejected("Resolution must link a contradiction to supporting evidence")
        if evidence[support].order <= evidence[contradiction].order:
            raise Rejected("Resolution requires later supporting evidence")
    unresolved = set(new.contradicting) - dict(new.resolutions).keys()
    if new.status in {H.WEAKENED, H.ELIMINATED} and not unresolved:
        raise Rejected("Weakening or elimination requires unresolved contradictions")
    if new.status == H.CONFIRMED and unresolved:
        raise Rejected("Unresolved contradictions prevent confirmation")
    if old.status == H.ELIMINATED and new.status == H.SUPPORTED:
        later = {e.id for e in session.evidence if e.order > old.eliminated_at}
        if not (set(new.supporting) - set(old.supporting)) & later:
            raise Rejected("Reopening requires new support recorded after elimination")


def verify_recommendation(session, candidate):
    verify_references(session, candidate.evidence_ids + candidate.acknowledged_contradictions)
    if not candidate.evidence_ids:
        raise Rejected("Recommendation requires evidence")
    hypothesis = next((h for h in session.hypotheses if h.id == candidate.hypothesis_id), None)
    if hypothesis is None or hypothesis.status not in {H.SUPPORTED, H.CONFIRMED}:
        raise Rejected("Recommendation requires a supported or confirmed hypothesis")
    if not set(hypothesis.supporting) & set(candidate.evidence_ids):
        raise Rejected("Recommendation must cite support for its selected hypothesis")
    unresolved = set(hypothesis.contradicting) - dict(hypothesis.resolutions).keys()
    if set(candidate.acknowledged_contradictions) != unresolved:
        raise Rejected("Recommendation must surface all unresolved contradictions")
    return ()
