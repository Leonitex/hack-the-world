# Milestone 1 diagnostic core

Requires Python 3.11 or later. Uses only the standard library; nothing needs to
be installed. Run from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m examples.no_display
```

The example is a scripted fixture. The engine contains no device-specific
decisions, model loop, provider integration, or external IO.

## State ownership and evidence flow

`DiagnosticSession(problem, max_turns=50, max_completion_attempts=3)` creates one
in-memory session. `execute(action, arguments)` is its only mutation interface.
It returns an `ActionResult` with an immutable session snapshot, an optional new
record ID, and optional completion verification. `snapshot` is read-only.

- `models.py` defines immutable records and statuses.
- `contracts.py` defines the action vocabulary and validates exact fields/types.
- `engine.py` assigns IDs, records results, applies actions, and enforces budgets.
- `verification.py` validates references, transitions, confirmation, and completion.

Application code records real user/tool observations with source and provenance.
Evidence IDs combine the session UUID with a monotonic sequence. Evidence also
has an explicit insertion order; IDs never change during the session. Provenance
is a nonempty string-to-string mapping copied into immutable pairs. Sources are
nonempty extensible names such as `user_text`, `diagnostic_test`, or
`image_observation`. No confidence score is fabricated.

Hypotheses reference evidence IDs. A proposed update is built separately, verified,
and only then committed. Evidence, support references, and contradiction references
are append-only. Snapshots do not grant callers a route to mutate authoritative
state. This is an application API boundary, not a sandbox for hostile Python code
running inside the same process.

## Action contracts

All listed fields are required, even empty reference lists or resolution maps.
Unknown fields/actions, blank text, duplicate references, and invalid types are
rejected with `Rejected`. Limits and session statuses are never tool arguments.

| Action | Fields | Effect |
| --- | --- | --- |
| `record_evidence` | `source`, `statement`, `provenance` | Append an observation while investigating |
| `propose_hypothesis` | `cause` | Create a `possible` hypothesis |
| `update_hypothesis` | `hypothesis_id`, `status`, `supporting`, `contradicting`, `resolutions`, `rationale` | Verify and apply an assessment; reference lists accumulate |
| `request_diagnostic_test` | `action`, `observations` | Create a concrete request and enter `needs_input` |
| `record_test_result` | `request_id`, `statement`, `provenance` | Record the matching result as `diagnostic_test`, then resume |
| `request_user_evidence` | `action`, `observations` | Request an observation and enter `needs_input` |
| `provide_user_evidence` | `request_id`, `source`, `statement`, `provenance` | Record the matching observation, then resume |
| `submit_recommendation` | `hypothesis_id`, `action`, `evidence_ids`, `acknowledged_contradictions` | Attempt mandatory completion verification |

Reference fields are lists/tuples of strings. `observations` must be a nonempty
list/tuple of distinct, nonblank questions. `resolutions` is a mapping from a
contradicting evidence ID to a later supporting evidence ID; use `{}` when none
are being resolved. `rationale` explains the assessment and any resolutions.

`contracts.py` separates the field definitions into two exposure classes:

- `MODEL_ACTION_FIELDS`: `propose_hypothesis`, `update_hypothesis`,
  `request_diagnostic_test`, `request_user_evidence`, and `submit_recommendation`.
- `TRUSTED_INGESTION_ACTION_FIELDS`: `record_evidence`, `record_test_result`,
  and `provide_user_evidence`.

Future adapters must enumerate only `MODEL_ACTION_FIELDS` for model tools.
The combined `ACTION_FIELDS` is derived from these groups for the existing
application API and argument validator. An import-time guard rejects overlapping
groups; deriving the combined vocabulary leaves no action unclassified. This
enforces the classification, not caller authentication: `execute()` remains the
trusted application entry point and accepts both classes with unchanged validation.

Future adapters must distinguish proposals from observations: the model may ask
for a test or propose an assessment, but trusted application code must obtain the
real user/tool result before invoking an evidence-writing action. The core checks
provenance structure, not its truth or identity. Do not expose an unrestricted
evidence writer to a model as proof that a physical action happened.

## Mandatory hypothesis verification

| From | Allowed destinations |
| --- | --- |
| `possible` | `possible`, `supported`, `weakened`, `eliminated`, `confirmed` |
| `supported` | `supported`, `weakened`, `eliminated`, `confirmed` |
| `weakened` | `weakened`, `supported`, `eliminated`, `confirmed` |
| `eliminated` | `eliminated`, `supported` |
| `confirmed` | `confirmed`, `weakened`, `eliminated` |

Every reference must exist in the current session. The same observation cannot
both support and contradict one hypothesis. `supported` and `confirmed` require
support; `weakened` and `eliminated` require unresolved contradictions.
Confirmation requires every contradiction to be resolved. A resolution must link
an existing contradiction to supporting evidence recorded later, with a nonempty
update rationale. Original contradictions remain visible.

Reopening an eliminated hypothesis requires a separate transition to `supported`
using new support recorded after elimination. Only a subsequent verified action
may confirm it. A direct `eliminated -> confirmed` jump is always rejected, even
if the same call supplies new support.

## Completion and lifecycle

`submit_recommendation` internally enters `awaiting_verification` and runs the
verifier synchronously. There is no `complete`, `set_status`, `verified=true`, or
optional verification action. Completion requires existing evidence, a supported
or confirmed hypothesis, and at least one citation supporting that hypothesis.
Every unresolved contradiction must be explicitly acknowledged in the recommendation.
A recommendation on a supported hypothesis is an evidence-backed next action;
completion does not promote that hypothesis to confirmed or eliminate alternatives.

Each completion attempt records its candidate (when structurally valid), pass/fail,
and rejection reasons. A failed attempt returns verification feedback while keeping
the session investigating. The caller can request concrete additional input rather
than guess. At the configured failed-attempt limit, the application pauses the session.

`needs_input` accepts only the matching user-evidence/test-result action and request
ID. Recording the result and resuming are one operation. Stale, mismatched, or
unsolicited results are rejected. Evidence and hypotheses survive resume.

Every attempted action on a live session consumes one turn, including invalid
actions. A valid completion on the last available turn succeeds. Otherwise the last
turn pauses the session after any valid action is committed. Completion attempts
(including malformed submissions) also consume their separate lifetime budget.
Handoffs do not reset either budget. Rejections never partially commit diagnostic
records, although counters and a budget-triggered pause can change.

`completed` and `paused` are terminal for this milestone. `pause_reason` identifies
`turn_limit` or `completion_attempt_limit`; the caller must return control to the
human. There is no model-accessible reset. Ordinary human handoffs use the resumable
`needs_input` state, not `paused`.

## Limits and Milestone 2 boundary

- In-memory, synchronous, single-caller operation only. No persistence or concurrent
  mutation support; restart loses the session. Persistence round-trip is therefore
  outside this milestone.
- Deterministic checks establish structural support and consistency. They cannot
  establish the truth, causal relevance, physical safety, or sufficiency of a text
  claim. A caller can still submit a mistaken observation or rationale.
- No timestamps are needed: evidence insertion order provides the specified order
  and supports the new-evidence gates. IDs are generated with UUIDs; tests assert
  invariants rather than random UUID values.
- There is no UI, network, provider, credential loading, model verifier, retry loop,
  or GitHub Actions configuration.

Milestone 2 should derive provider schemas from these contracts, bind observations
to trusted execution/user input, and return the actual `ActionResult` or rejection
to the model. Add mocked provider-loop tests, error pausing, and validated
persistence/resume without giving model output a direct session-write path.
