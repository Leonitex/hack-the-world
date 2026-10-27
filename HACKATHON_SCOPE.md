# Hackathon Scope

## Event

Meta Global AI Developer Hackathon 2026

## Track

**Indie Developer — Build for Your World**

## New-work boundary

This repository was created specifically for the hackathon. The implementation, product design, demo flow, tests, and documentation presented from this repository are intended to be hackathon-period work.

Prior experience and lessons from unrelated projects may inform engineering decisions, but prior project code, private assets, and pre-existing product functionality are not being presented as hackathon work.

## Problem statement

People troubleshooting computers and consumer technology often receive advice that jumps too quickly from a symptom to a diagnosis. Real troubleshooting is iterative: gather evidence, preserve uncertainty, choose the next useful test, and verify the result.

Hack the World will demonstrate an AI agent that follows that evidence-driven process.

## In scope for the MVP

- A focused technology troubleshooting scenario suitable for a live demo.
- Multimodal input: at minimum text plus image evidence when available.
- A structured evidence ledger.
- Multiple competing diagnostic hypotheses.
- An agent decision for the next useful question or test.
- Updating hypothesis confidence/status after new evidence.
- A final recommendation that cites the evidence used.
- Meta model integration through an approved hackathon route.
- A public, reproducible repository and a three-minute demo.

## Stretch goals

- Visual grounding/segmentation of relevant components.
- Voice input/transcription.
- Multiple technology categories beyond the initial scenario.
- Provider failover between hackathon inference partners.
- Session export showing the diagnostic evidence trail.
- Additional agent evaluation and reliability tests.

## Explicitly out of scope for the first build

- Medical, mental-health, political, military, or other prohibited use cases.
- Generic chat or basic RAG as the core product.
- A one-shot "upload an image and receive a diagnosis" experience.
- Autonomous physical repair actions.
- Claims of certainty when evidence is incomplete.
- Reusing existing private-project code and presenting it as new hackathon work.

## Success criteria

The MVP succeeds when a judge can watch one troubleshooting session and clearly see that:

1. the agent starts uncertain;
2. it records evidence;
3. it keeps more than one plausible explanation;
4. it chooses a meaningful next diagnostic step;
5. new evidence changes the hypothesis state; and
6. the final recommendation is visibly grounded in that accumulated evidence.
