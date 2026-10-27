# Three-Minute Demo Plan

## Demo objective

Prove that Hack the World is not a one-shot image analyzer. The audience should see the agent investigate an ambiguous technology problem, choose useful tests, update its beliefs, and reach an evidence-backed recommendation.

## Primary scenario

**Computer powers on, fans spin, but there is no display.**

This scenario is useful because several causes can initially fit the symptom, allowing the demo to show real hypothesis elimination.

## Target flow

### 0:00–0:20 — Hook

Show the problem and the product promise:

> "Instead of guessing what is wrong from one symptom, Hack the World investigates like a technician: gather evidence, test hypotheses, verify."

User enters the symptom and, if useful, adds an image.

### 0:20–0:50 — Observe and hypothesize

The UI shows:
- evidence recorded from the user;
- several plausible causes;
- uncertainty is explicit rather than hidden.

Example candidates might include display path, memory seating, power delivery, or another hardware state appropriate to the evidence.

### 0:50–1:30 — First diagnostic action

The agent selects the next useful test and explains why that test separates competing hypotheses.

The user supplies the result.

The UI visibly updates:
- new evidence added;
- one hypothesis strengthened;
- another weakened or eliminated.

### 1:30–2:05 — Second evidence step

The agent chooses the next diagnostic step based on the updated state, not from a fixed script.

If visual grounding is implemented, use it here to indicate the relevant component/region.

### 2:05–2:30 — Recommendation

Show the final recommendation with the evidence that supports it. Avoid unsupported certainty if the session has not proved a single cause.

### 2:30–2:50 — Under the hood

Briefly show:
- evidence ledger;
- hypothesis state;
- agent orchestration;
- Meta model(s) used and where they participate.

### 2:50–3:00 — Close

One sentence on impact:

> "Hack the World turns AI from a guess generator into an evidence-driven troubleshooting partner."

## Demo acceptance criteria

Before recording, the scenario must:
- run end to end without manual code edits;
- visibly start with uncertainty;
- include at least two plausible hypotheses;
- include at least one agent-selected follow-up test;
- visibly update hypothesis state from new evidence;
- produce an evidence-linked recommendation;
- clearly identify the Meta tooling involved;
- complete comfortably inside three minutes.

## Recording rule

Only demonstrate features, code, and functionality created during the hackathon build period, and ensure the public repository matches what is shown in the video.
