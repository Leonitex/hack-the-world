# Architecture

## Design principle

Hack the World separates **model judgment**, **real actions**, **diagnostic state**, and **verification**.

The model decides which diagnostic action would be most useful next. Application code executes that action, records what actually happened, and returns the result to the model. The application—not the model—owns the authoritative evidence and hypothesis state.

Verification gates sit in the path to important state transitions so the model cannot simply choose to skip them.

## Agent loop

```text
User problem / new evidence
        ↓
Model decides the next diagnostic tool/action
        ↓
Application validates and executes the action
        ↓
Real result is recorded in the evidence ledger
        ↓
Result returns to the model
        ↓
Model decides again
        ↓
Completion attempt → deterministic verification gate
                     ↓ pass                 ↓ fail
              recommendation         feedback to model
                                      or needs_input
```

The loop stops when:
- a recommendation passes the required verification gates;
- the agent reaches a `needs_input` state and requires the user to perform/provide something;
- a configured turn/attempt limit is reached; or
- an unrecoverable provider/application error pauses the run safely.

## Proposed components

### 1. Client

Responsibilities:
- capture the user's symptom description;
- accept image evidence;
- display current evidence and hypotheses;
- present the next diagnostic instruction;
- collect the user's test result;
- visibly show the operational timeline without exposing private chain-of-thought.

The initial client should optimize for demo clarity rather than feature breadth.

### 2. Diagnostic orchestrator

The orchestrator owns the model/tool loop and advances the session.

Responsibilities:
- present the model with the current task, state summary, and available tools;
- let the model choose the next tool rather than hard-coding a fixed scenario sequence;
- validate tool arguments;
- execute approved tool calls;
- return real tool results to the model;
- save state after every successful transition;
- enforce turn/attempt limits;
- pause safely on provider failure or `needs_input`.

### 3. Evidence ledger

Each evidence item should have a stable ID and record:
- source type (`user_text`, `image_observation`, `diagnostic_test`, `visual_grounding`, etc.);
- statement/result;
- timestamp/order;
- provenance metadata;
- reliability/confidence metadata where useful.

Hypotheses refer to evidence IDs rather than relying only on conversational context.

### 4. Hypothesis state

A hypothesis should contain:
- ID;
- candidate cause;
- status: `possible`, `supported`, `weakened`, `eliminated`, or `confirmed`;
- supporting evidence IDs;
- contradicting evidence IDs;
- rationale suitable for the UI.

The model may propose changes, but application code validates references and owns the state transition.

### 5. Diagnostic tools

The first provider-independent tool surface should be small and generic.

Model-selectable tools are exactly the actions in `MODEL_ACTION_FIELDS` (`diagnostic_core/contracts.py`):
- `propose_hypothesis`;
- `update_hypothesis`;
- `request_diagnostic_test`;
- `request_user_evidence`;
- `submit_recommendation`.

Application/trusted-caller only ingestion actions. These MUST NOT be presented to the model as callable tools:
- `record_evidence`;
- `record_test_result`;
- `provide_user_evidence`.

Tool definitions should not hard-code the primary demo scenario. The model chooses which valid model-selectable tool to call next.

### 6. Verification layer

Verification is **not** an optional tool the model can choose to call. Checks run automatically at the moments the agent attempts important transitions.

Initial deterministic checks should include:
- every cited evidence ID exists;
- a `confirmed` hypothesis has supporting evidence;
- a recommendation cites evidence from the current session;
- eliminated hypotheses cannot be confirmed without a valid later transition;
- unresolved contradictory evidence is surfaced rather than silently ignored;
- required fields/tool arguments are valid;
- repeated failed completion attempts eventually hand control back to the user instead of looping forever.

Later, a model-based claim/support check may complement deterministic checks, but deterministic invariants remain authoritative.

### 7. `needs_input` handoff

When the agent cannot distinguish remaining hypotheses from available evidence, it should request a concrete user action or additional observation and pause the run as `needs_input`.

Example:

```text
needs_input:
  action: Reseat one RAM module and power on again
  requested_observations:
    - Did the display behavior change?
    - Did a diagnostic LED or beep pattern change?
```

The session resumes when the result is supplied; it does not restart from scratch.

### 8. Meta model adapter

Provider-specific API calls sit behind a common interface.

For the hosted Meta Model API route, the current primary target is `muse-spark-1.3`, which supports multimodal input and tool calling. Open-weight inference through Baseten, Modal, or Fireworks can later sit behind the same boundary without changing the diagnostic state engine.

The adapter should support:
- tool/function calling;
- multimodal observation/reasoning;
- structured output where appropriate;
- bounded retries and safe failure;
- provider/model metadata for the demo and validation log.

### 9. Visual grounding adapter

Where it adds real diagnostic value, SAM 3.1 can identify or segment a component/region requested by the agent.

Example: instead of merely saying "check the RAM," the product can visually indicate the relevant component region when the image provides enough information.

SAM is a supporting tool, not the core product and not something to invoke on every turn.

## Initial session schema

```json
{
  "session_id": "...",
  "problem": "Computer powers on but has no display",
  "status": "investigating",
  "turn_count": 0,
  "evidence": [],
  "hypotheses": [],
  "next_action": null,
  "completion_attempts": 0
}
```

Suggested session statuses:
- `investigating`
- `needs_input`
- `awaiting_verification` (internal/transient only; see below)
- `completed`
- `paused`

`awaiting_verification` is an internal/transient state during the synchronous `submit_recommendation` verification transition, not a stable externally observable session state that a UI should depend on.

## Reliability rules

1. Never convert a model guess directly into a confirmed diagnosis.
2. Let the model choose among valid tools; do not encode the demo as a fixed decision tree.
3. Preserve alternative hypotheses until evidence weakens or eliminates them.
4. Every final recommendation must reference accumulated evidence.
5. Completion attempts pass through non-skippable verification gates.
6. If evidence is insufficient, enter `needs_input` rather than inventing certainty.
7. Bound turns/retries so a confused agent cannot loop forever.
8. Provider/model output must be validated before it mutates authoritative session state.

## MVP architecture decision

Start with the provider-independent state engine, diagnostic tool contracts, deterministic verification gates, and local tests. Then connect one Meta model and show one end-to-end agent-selected troubleshooting session in a simple web UI.

Do not add segmentation, voice, multi-provider failover, or broad device coverage until that loop works clearly in the judge-facing demo.

## Current Meta workshop alignment

The October 27 Agents 101 workshop teaches the same core split used here: the model chooses a tool, code executes it, the real result returns to the model, and progress is persisted. The published Session 2 material places verification inside tool transitions so the model cannot skip it, supports `needs_input` human handoff, and limits repeated refusals/loops. Hack the World adapts those general patterns to evidence-driven technology troubleshooting rather than copying the workshop application.