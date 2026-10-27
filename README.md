# Hack the World

**Hack the World** is an evidence-driven multimodal AI diagnostic agent for real-world technology troubleshooting, created for the **Meta Global AI Developer Hackathon 2026**.

> **Hackathon work declaration:** Implementation in this repository is being developed during the official hackathon build period. The repository was created specifically for this event so the work can be clearly distinguished from prior projects.

## Problem

Technology troubleshooting often fails because people jump from a symptom to a conclusion. A photo or error message can suggest possibilities, but reliable diagnosis usually requires gathering more evidence, testing competing explanations, and verifying the result.

Hack the World is designed around that diagnostic process rather than a one-shot image answer.

## Core loop

**Observe → Hypothesize → Ask → Verify → Recommend**

1. **Observe** — collect the user's symptoms, images, and other evidence.
2. **Hypothesize** — maintain multiple plausible causes instead of committing too early.
3. **Ask** — choose the next useful diagnostic question or test.
4. **Verify** — incorporate the result and update or eliminate hypotheses.
5. **Recommend** — provide the next action only when the evidence supports it.

## Hackathon target

The first working demo will focus on a narrow but convincing technology-support scenario, such as a computer that powers on but has no display. The goal is to demonstrate an agent that becomes more certain through evidence rather than simply generating a diagnosis from a single image.

## Meta AI direction

The project is being designed to use Meta AI tooling where it materially improves the diagnostic workflow, including Meta multimodal/open-weight models for reasoning and, where appropriate, segmentation or visual grounding. Provider-specific integrations will be kept behind adapters so the demo can use the best hackathon-available inference route without changing the diagnostic core.

## Repository map

- [`HACKATHON_SCOPE.md`](HACKATHON_SCOPE.md) — what is in and out of scope for the event
- [`docs/architecture.md`](docs/architecture.md) — system and agent architecture
- [`docs/judging-strategy.md`](docs/judging-strategy.md) — how the build maps to the judging rubric
- [`docs/demo-plan.md`](docs/demo-plan.md) — the three-minute demo target

## Status

**Foundation phase:** scope and architecture are being established before implementation begins.

## Team

**Leonitex** — Indie Developer track
