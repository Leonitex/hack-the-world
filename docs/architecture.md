# Architecture

## Design principle

Hack the World separates **diagnostic state** from **model output**. The model proposes observations, hypotheses, and next actions, but the application stores the evidence trail explicitly so the reasoning process can be inspected, tested, and demonstrated.

## Core loop

```text
User evidence
   ↓
Observe
   ↓
Evidence ledger
   ↓
Hypothesize
   ↓
Competing hypotheses
   ↓
Ask / choose next test
   ↓
New evidence
   ↓
Verify / update state
   ↓
Recommend when sufficiently supported
```

## Proposed components

### 1. Client

Responsibilities:
- capture the user's symptom description;
- accept image evidence;
- display current evidence and hypotheses;
- present the next diagnostic instruction;
- collect the user's result.

The initial client should optimize for demo clarity rather than feature breadth.

### 2. Diagnostic orchestrator

The orchestrator owns the session state and advances the agent through the diagnostic loop.

Responsibilities:
- normalize evidence;
- call the reasoning adapter;
- validate structured model responses;
- store hypotheses and evidence links;
- decide whether another test is required;
- prevent the UI from treating an unsupported hypothesis as a confirmed diagnosis.

### 3. Evidence ledger

Each evidence item should have a stable ID and record:
- source type (user text, image observation, test result, etc.);
- statement;
- timestamp/order;
- confidence or reliability metadata when useful.

Hypotheses refer to evidence IDs rather than relying only on conversational context.

### 4. Hypothesis state

A hypothesis should contain:
- ID;
- candidate cause;
- status: `possible`, `supported`, `weakened`, `eliminated`, or `confirmed`;
- supporting evidence IDs;
- contradicting evidence IDs;
- rationale suitable for the UI.

The application, not the language model alone, owns these state transitions.

### 5. Meta model adapter

Provider-specific API calls sit behind a common interface. The first adapter should support the Meta model route available to us during the hackathon; open-weight inference through Baseten, Modal, or Fireworks can be added without rewriting the diagnostic engine.

Expected capabilities:
- multimodal observation/reasoning;
- structured JSON responses;
- next-test selection;
- final evidence-grounded recommendation.

### 6. Visual grounding adapter

Where access and time permit, SAM 3.1 or another eligible Meta visual tool can identify/segment the region relevant to a diagnostic instruction. This is a supporting capability, not the entire product.

Example: instead of merely saying "check the RAM," the UI can visually indicate the relevant component region when the image provides enough information.

## Initial session schema

```json
{
  "session_id": "...",
  "problem": "Computer powers on but has no display",
  "evidence": [],
  "hypotheses": [],
  "next_action": null,
  "status": "investigating"
}
```

## Reliability rules

1. Never convert a model guess directly into a confirmed diagnosis.
2. Preserve alternative hypotheses until evidence weakens or eliminates them.
3. Every final recommendation must reference accumulated evidence.
4. If evidence is insufficient, ask for another diagnostic step rather than invent certainty.
5. Keep provider/model output behind validation so malformed responses cannot silently corrupt session state.

## MVP architecture decision

Start with one server-side orchestrator, one model adapter, one narrow demo scenario, and a simple web UI. Add segmentation, voice, multi-provider support, and broader device coverage only after the core diagnostic loop works end to end.
