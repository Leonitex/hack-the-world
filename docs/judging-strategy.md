# Judging Strategy

The build is optimized for the published Meta Global AI Developer Hackathon rubric rather than for maximum feature count.

## 1. Impact — 30%

### Goal
Show a problem that is common, costly in time, and familiar from real-world technology support: people often do not know what evidence matters when a device fails.

### What judges should see
- a user with an ambiguous real problem;
- an agent that reduces uncertainty step by step;
- guidance that a non-expert can follow;
- a result that would save unnecessary guessing, replacement, or technician time.

### Build implication
Prefer one convincing end-to-end scenario over a broad but shallow catalog of device types.

## 2. Use of Meta AI Tooling — 25%

### Goal
Use Meta models as essential parts of the diagnostic workflow, not as a cosmetic chat layer.

### Target uses
- multimodal reasoning over symptom descriptions and images;
- open-weight Meta model inference for repeated agent steps;
- structured next-test selection;
- visual grounding/segmentation where it materially helps the user locate a component or region;
- optional voice transcription if it improves the demo.

### Build implication
The demo should make it obvious what the Meta model is doing at each stage.

## 3. Technical Depth & Execution — 20%

### Goal
Demonstrate that the system is engineered around reliability and inspectability.

### Evidence
- explicit evidence ledger;
- structured hypotheses linked to evidence;
- validated model responses;
- deterministic session state transitions around nondeterministic model calls;
- tests for evidence and hypothesis updates;
- clear separation between orchestration and inference providers.

### Build implication
Do not hide the agent logic inside one giant prompt.

## 4. Demo — 25%

### Goal
Make the three-minute video understandable without requiring judges to read documentation first.

### Demo story
1. Show the ambiguous problem.
2. Show that the agent does **not** immediately claim a diagnosis.
3. Display multiple candidate causes.
4. Perform one or two targeted tests.
5. Show hypotheses changing as evidence arrives.
6. Show the final evidence-backed recommendation.
7. Briefly reveal the evidence ledger/architecture and identify the Meta tooling used.

### Build implication
Every feature must earn its place in this three-minute story.

## Bonus-prize alignment

### Best Agentic Use-Case
The core product is explicitly multi-step: the agent chooses diagnostic actions, receives results, updates state, and decides what to do next.

### Best Build on Meta Open Weight Models
If the final deployment uses an eligible Meta open-weight model such as Muse Spark Open, document the exact model and inference path clearly in the submission.

## Anti-project guardrail

The project must not become a simple image analyzer. An image is evidence, not the product. The differentiator is the iterative diagnostic loop and the visible state change driven by new evidence.

## Priority order

When time is constrained, prioritize:

1. working end-to-end diagnostic loop;
2. strong Meta model integration;
3. clear, impressive demo;
4. reliability tests and evidence visualization;
5. visual grounding/segmentation;
6. voice and additional scenarios.
