# Hack the World — Project Rules, Workshop Guidance, and Operating Notes

**Project:** Hack the World  
**Repository:** `Leonitex/hack-the-world`  
**Track:** Indie Developer — Build for Your World  
**Event:** Meta Global AI Developer Hackathon 2026  
**Last updated:** 2026-10-28

---

## 1. Purpose of this document

This file is the working source of truth for the rules, workshop lessons, judging advice, architecture guardrails, and project-specific decisions that should guide development of **Hack the World**.

It deliberately separates four kinds of information:

- **OFFICIAL RULE** — competition requirement or current official event information.
- **META / WORKSHOP GUIDANCE** — advice or implementation patterns taught by Meta during the hackathon.
- **PROJECT DECISION** — an engineering or workflow choice made specifically for Hack the World.
- **OPEN QUESTION** — something that should be confirmed with hackathon staff rather than guessed.

If these ever conflict, use this order of authority:

1. Current official hackathon rules / submission form.
2. Current Meta Model API documentation.
3. Current workshop or office-hours clarification from Meta/Cerebral Valley.
4. This document and other repository documentation.
5. AI-agent suggestions.

Never let an AI coding agent, generated documentation, old transcript, or stale cached information override newer official rules.

---

# 2. Event facts and hard competition rules

## 2.1 Event and timeline

**OFFICIAL**

- Event: Meta Global AI Developer Hackathon 2026.
- Hackathon begins: **October 26, 2026**.
- Workshops and Discord office hours: **October 27 through November 4, 2026**.
- Submission deadline: **November 4, 2026 at 9:00 PM ET**.
- In Trinidad and Tobago, this corresponds to **10:00 PM local time on November 4**, because U.S. Eastern Time is EST by then.
- Judging: November 4–8.
- Closing ceremony / finals: November 9.
- Prize pool: **US$1,000,000**.

The event page says dates may change, so re-check the official event page before final submission.

## 2.2 Track

**PROJECT DECISION**

Hack the World is entered in:

**Indie Developer — Build for Your World**

The project fits this theme because it is based on a firsthand problem domain: real-world computer and technology troubleshooting.

## 2.3 Meta model requirement

**OFFICIAL / CORE ELIGIBILITY**

The submitted product must meaningfully use Meta AI/models. The Meta model cannot be a cosmetic label or an irrelevant extra.

For Hack the World, the intended meaningful use is:

- a Muse model makes the next diagnostic decision;
- it reasons over accumulated evidence and competing hypotheses;
- it selects a question, diagnostic test, hypothesis update, or completion attempt;
- SAM may later provide visual grounding when that materially helps;
- other Meta capabilities may be added only if they improve the product or demo.

Using Codex, ChatGPT, Muse Code, or another coding assistant to **build** the project is separate from the requirement that the **product itself** meaningfully uses Meta models.

## 2.4 Public repository and submission provenance

**OFFICIAL / PROJECT GUARDRAIL**

The submission uses a public repository created specifically for this hackathon.

Do not present pre-hackathon code, private assets, or existing product functionality as new hackathon work.

Allowed:

- prior experience;
- lessons learned from other projects;
- normal open-source dependencies with compatible licenses;
- AI-generated code produced during the hackathon;
- standard development tools.

Not allowed for our submission:

- copying substantial code from CyberKnight, JarvisCall, Echo Atlas, CatScan, or another older Leonitex project and presenting it as hackathon-created;
- misrepresenting when features were built;
- using assets/code we do not have the right to use.

Keep Git history, validation notes, and milestone PRs clean enough to establish provenance.

## 2.5 Team size

**OFFICIAL**

Maximum team size: **4 people**.

Current project setup is solo, which is allowed.

## 2.6 Final submission

**OFFICIAL / CURRENT PLAN**

The final submission must include the required hackathon materials, including:

- public repository;
- accessible demo video;
- team/member information;
- any other fields required by the final submission form.

The current demo target is approximately **3 minutes**.

Before submission, re-open the actual submission form and verify every requirement rather than relying on this file.

---

# 3. Judging strategy

The project should be optimized for the published judging rubric rather than maximum feature count.

## Impact — 30%

Judges should understand:

- the problem is common and real;
- non-experts often do not know which evidence matters;
- bad troubleshooting jumps too quickly from symptom to diagnosis;
- a structured diagnostic agent can reduce wasted time, unnecessary part replacement, and guesswork.

**Build implication:** one convincing end-to-end troubleshooting experience is more valuable than a shallow catalog of many device types.

## Meta AI Tooling — 25%

Meta models must be visibly important to the workflow.

Good evidence:

- model-selected diagnostic actions;
- multimodal reasoning;
- structured tool use;
- evidence-aware hypothesis updates;
- SAM visual grounding when useful;
- open-weight Meta model use if it becomes a real part of the product.

**Build implication:** the demo should make it obvious what the Meta model is doing.

## Technical Depth & Execution — 20%

Show engineering, not merely prompting.

Important evidence:

- explicit evidence ledger;
- competing hypotheses;
- structured state;
- validated tool calls;
- deterministic verification around nondeterministic model output;
- bounded loops/retries;
- tests;
- separation of model/provider code from authoritative state.

**Build implication:** do not hide the product inside one giant system prompt.

## Demo — 25%

The demo should be understandable without reading the repository.

The story should visibly move from:

**uncertainty → evidence → competing explanations → chosen test → new evidence → updated state → supported recommendation**

Every feature should earn its place in this story.

---

# 4. Anti-project and scope guardrails

The hackathon materials warn against simplistic or unsuitable AI projects. Relevant examples include basic RAG, generic chatbots, simple image analyzers, and several sensitive-domain products.

For Hack the World:

## Never let the project become a one-shot image analyzer

Bad version:

> Upload image → AI guesses the fault.

Our intended version:

> Observe → form competing hypotheses → choose the next useful test → gather real evidence → update state → verify → recommend.

An image is **evidence**, not the product.

## Explicitly out of scope

- medical diagnosis;
- mental-health diagnosis;
- political or military decision systems;
- autonomous physical repair;
- unsupported claims of certainty;
- basic RAG as the product;
- generic chatbot behavior as the product;
- fixed hard-coded troubleshooting tree disguised as an agent.

---

# 5. Core product definition

## Project pitch

**Hack the World is a multimodal AI diagnostic agent that investigates real-world technology problems by gathering evidence, testing competing hypotheses, and guiding users through verifiable troubleshooting steps.**

## Core loop

```text
OBSERVE
   ↓
HYPOTHESIZE
   ↓
ASK / SELECT TEST
   ↓
VERIFY REAL RESULT
   ↓
UPDATE STATE
   ↓
RECOMMEND OR CONTINUE
```

The agent should begin uncertain.

It should not produce a confident final diagnosis from the initial symptom unless evidence genuinely justifies it.

---

# 6. Primary demo scenario

Current primary scenario:

> A desktop/computer powers on and the fans spin, but there is no display.

The system should initially consider multiple plausible causes such as:

- display path/cable;
- monitor/input;
- RAM;
- GPU;
- power or other relevant hardware causes.

The exact sequence must **not** be hard-coded.

The model should choose the next useful test based on the current state.

The user then supplies a real result, and the hypothesis state changes.

---

# 7. Meta Agents workshop lessons

These are important implementation patterns taught in the hackathon workshops.

## 7.1 An agent is a model using tools in a loop

**META / WORKSHOP GUIDANCE**

General pattern:

```text
1. Model decides what action/tool to use.
2. Application code validates and executes the action for real.
3. The real result goes back to the model.
4. The model decides again.
```

For Hack the World:

```text
Muse
  ↓ chooses action
Application
  ↓ validates / executes
Real user or tool result
  ↓
Evidence ledger
  ↓
Muse receives result
  ↓
next decision
```

Do not fake the result of a physical diagnostic action.

## 7.2 Authoritative state belongs to the application

**META / WORKSHOP GUIDANCE + PROJECT DECISION**

The LLM is probabilistic and should not be the durable database of the diagnosis.

The application owns:

- evidence;
- provenance;
- hypotheses;
- status transitions;
- turn counters;
- completion attempts;
- verification results.

The model supplies judgment about what to investigate next.

## 7.3 Verification must not be optional

**META / WORKSHOP GUIDANCE**

A critical lesson from the workshop:

Do **not** expose a separate `verify` tool and hope the model remembers to call it.

Instead, verification should sit **inside important transitions**.

For example:

```text
model calls submit_recommendation
        ↓
application runs required verifier automatically
        ↓
pass → complete
fail → return feedback / continue / needs_input
```

The model cannot skip this gate.

## 7.4 `needs_input` is a legitimate stopping state

**META / WORKSHOP GUIDANCE**

If the agent requires a user to perform a real action or provide new evidence:

- enter `needs_input`;
- stop the model loop;
- show the requested action;
- wait for the real result;
- resume the same session afterward.

Do not invent a result merely to keep the agent running.

## 7.5 Bound loops and failed completion attempts

**META / WORKSHOP GUIDANCE**

Every agent loop needs limits.

Hack the World should bound:

- total diagnostic turns;
- provider/model steps;
- completion attempts;
- retry attempts after malformed responses or provider errors.

A confused model must not spin forever.

Repeated failure should hand control back to the user/application.

## 7.6 Persist or preserve progress

Workshop guidance emphasizes preserving progress each turn.

Milestone 1 is intentionally in-memory, but Milestone 2+ should add validated persistence/resume without allowing the model to write arbitrary session state.

---

# 8. Model-selectable actions vs trusted evidence ingestion

This boundary is one of the most important rules in the project.

## Model may select

```text
propose_hypothesis
update_hypothesis
request_diagnostic_test
request_user_evidence
submit_recommendation
```

## Model must NOT directly call

```text
record_evidence
record_test_result
provide_user_evidence
```

Those are trusted ingestion operations.

The model may decide **what evidence it wants**.

The model may not **manufacture the evidence**.

Example:

Wrong:

```text
Muse:
record_test_result(
  statement="The user reseated the RAM and the display returned."
)
```

Correct:

```text
Muse:
request_diagnostic_test("Reseat one RAM module and test again.")

Application:
status = needs_input

User:
"I reseated it. Still no display."

Application:
record_test_result(real user result)

Muse:
receives the real result and reasons again
```

Future provider adapters must enumerate tools from `MODEL_ACTION_FIELDS`, never from the combined application action vocabulary.

---

# 9. Current diagnostic-state rules

Milestone 1 established these states:

```text
investigating
needs_input
awaiting_verification
completed
paused
```

Hypothesis states:

```text
possible
supported
weakened
eliminated
confirmed
```

Important invariants:

1. Every evidence reference must exist in the same session.
2. The same evidence cannot simultaneously support and contradict the same hypothesis.
3. Supported/confirmed hypotheses require supporting evidence.
4. Weakened/eliminated hypotheses require contradictory evidence.
5. Unresolved contradictions block confirmation.
6. A final recommendation must cite actual supporting evidence.
7. Unresolved contradictions must be surfaced rather than hidden.
8. An eliminated hypothesis cannot jump directly to confirmed.
9. Reopening an eliminated hypothesis requires new supporting evidence recorded after elimination.
10. Final completion always passes through mandatory verification.
11. Turn/completion budgets survive `needs_input` handoffs.
12. Paused/completed states are terminal for the current core.

---

# 10. Reasoning visibility and UI

Do **not** expose private model chain-of-thought.

The judge-facing UI should instead show useful operational state such as:

```text
OBSERVED
HYPOTHESES
NEXT TEST
RESULT
UPDATED HYPOTHESES
FINAL RECOMMENDATION
EVIDENCE USED
```

This makes the agent inspectable without displaying hidden reasoning.

---

# 11. Demo guidance from kickoff

The kickoff emphasized thinking about **how the project will be presented to judges while it is being built**, rather than leaving the demo until the end.

Our interpretation:

For every significant feature ask:

1. What will the judge visibly see?
2. Which rubric category does this improve?
3. Can we demonstrate it reliably?
4. Is it more valuable than hardening the existing end-to-end loop?

Build the product and the demonstration story in parallel.

Avoid spending most of the hackathon on invisible infrastructure that never appears in the three-minute demo.

---

# 12. Demo structure

Current target:

### 0:00–0:20 — Hook
Show the ambiguous failure.

### 0:20–0:50 — Observe and hypothesize
Agent records evidence and shows multiple plausible explanations.

### 0:50–1:30 — First diagnostic action
Agent chooses the next useful test instead of guessing.

### 1:30–2:05 — New evidence
User/tool supplies result. Hypotheses visibly change.

SAM can appear here later if visual grounding genuinely improves the interaction.

### 2:05–2:30 — Recommendation
Agent provides evidence-backed action/recommendation.

### 2:30–2:50 — Under the hood
Briefly show evidence ledger, verification, and Meta tooling.

### 2:50–3:00 — Close

Core message:

> Hack the World turns AI from a guess generator into an evidence-driven troubleshooting partner.

---

# 13. Development workflow rules

## Branches and milestone gates

Use feature branches and milestone reviews.

Completed:

- Milestone 1 branch: `work/diagnostic-core`
- PR #2 merged to `main`
- Milestone 1 merge commit: `7371634b53f563c38e762044c38074aa00b669e8`
- Issue #1 completed

Current:

- Milestone 2 branch: `work/meta-agent-loop`
- Issue #3: Meta Model API agent loop

Do not merge milestone work until it is reviewed.

## Tests

Run deterministic local tests.

GitHub Actions are intentionally **not used** for this project because of the current workflow/usage constraint.

Do not claim a test passed unless it actually ran and the result was observed.

## AI coding agents

Current development approach:

- ChatGPT: planning, review, research, architecture challenge, tutoring.
- Codex CLI: primary implementation agent when appropriate.
- Muse Code: Meta-native coding/review tool used when useful.
- Meta Muse models: product reasoning engine.

Using Muse Code is not the same thing as using Muse inside the submitted product.

Do not switch coding agents just for appearances.

Use the tool that best fits the bounded task.

## Independent review rule

Never approve an AI-agent completion based only on its own report.

For milestone work:

- inspect the actual diff;
- inspect the tests;
- verify scope;
- check for hidden shortcuts;
- verify branch and commit;
- review architectural boundaries.

Do not agree with an agent simply because its output sounds confident.

---

# 14. No-secret rule

Never commit or paste into public project files:

- Meta API keys;
- payment credentials;
- passwords;
- tokens;
- signing keys;
- private `.env` values;
- personal/confidential information.

Use environment variables or appropriate local secret storage.

Before submission, scan the repository history as well as the current tree.

---

# 15. Muse Code notes

Current installed Muse Code version on the development PC:

```text
Muse Code 1.4.14 (1.4.14-R7309.1)
```

Current authenticated model observed:

```text
muse-spark-1.3-contributor
```

## Contributor mode

Meta documents that Contributor mode provides discounted usage in exchange for allowing Meta to use submitted prompts, code, files, context, and model responses to train future Meta models.

Therefore:

- acceptable for this public hackathon repository if used intentionally;
- do not submit personal, sensitive, confidential, credential, or secret material;
- switch Contributor mode off for anything that should not be used under those terms.

Contributor mode is a privacy/data-use tradeoff, not a hackathon eligibility requirement.

---

# 16. Current Meta model direction

Current official Meta documentation describes Muse Spark 1.3 as the latest Muse Spark model tuned for agentic workflows, tool use, long-horizon tasks, and coding.

Current project direction:

- begin Meta integration around `muse-spark-1.3`;
- keep the provider/model choice configurable;
- do not bake the model ID into diagnostic-state logic;
- evaluate another Meta model only when there is a concrete reason.

The architecture should allow changing model/provider configuration without rewriting the diagnostic core.

---

# 17. SAM guidance

SAM 3.1 is a **supporting capability**, not the product.

Use it only if it gives the user something materially useful, such as identifying the component/region the agent wants inspected.

Example:

Instead of only saying:

> Check the RAM.

A useful SAM-assisted step might highlight the RAM region in a supplied computer image.

Do not invoke segmentation merely to say that the project uses SAM.

---

# 18. Voice guidance

Voice transcription is a stretch goal.

Only add it if:

- the core diagnostic loop already works;
- it improves the demo or user experience;
- it does not endanger completion of the main submission.

Core agent reliability is more important than voice.

---

# 19. Open-weight model opportunity

The event includes Meta open-weight models and partner inference options.

Current partner information on the official event page includes Baseten, Modal, and Fireworks offers for selected participants.

Potential benefit:

Using an eligible Meta open-weight model meaningfully may support the **Best Build on Meta Open Weight Models** bonus category.

Do not bolt on an open-weight call merely for a prize checkbox.

If used, document:

- exact model;
- inference provider;
- what function it performs;
- why it is meaningful;
- where it appears in the demo.

---

# 20. Current build priority

When time is constrained, use this priority:

1. Reliable end-to-end diagnostic agent loop.
2. Meaningful Meta model integration.
3. Clear judge-facing UI/demo.
4. Evidence and verification visibility.
5. Reliability testing/hardening.
6. SAM if it improves the scenario.
7. Open-weight enhancement if meaningful.
8. Voice.
9. Additional troubleshooting categories.
10. Provider failover and other polish.

More features are not automatically better.

---

# 21. Things we should deliberately postpone

Until the core agent loop works:

- SAM implementation;
- voice;
- multi-provider failover;
- broad device support;
- elaborate persistence infrastructure;
- unnecessary agent frameworks;
- complex UI animation;
- fine-tuning unless a real need emerges;
- deployment optimization that the demo does not require.

---

# 22. Office-hours questions still worth confirming

These should be asked only if they have not already been answered by newer official materials.

1. Does use of Codex CLI or another non-Meta development assistant affect eligibility or judging in any way, assuming the submitted product itself meaningfully uses Meta models?

2. What exact threshold do judges use for “meaningful use” of Meta AI tooling?

3. What exact use qualifies a project for the Best Build on Meta Open Weight Models bonus?

4. Does our iterative multimodal diagnostic architecture clearly avoid the “simple image analyzer” anti-project category?

5. How should participant Model API credits interact with billing controls, and is there a supported hard spending cap?

6. Is a live API call required in the three-minute demo, or is a reproducible controlled recording acceptable when the underlying functionality is genuine?

7. Is Git history sufficient evidence of hackathon-period work, or do organizers recommend additional provenance documentation?

8. Must judges be able to run the repository without supplying their own API credentials?

---

# 23. Transcript-specific logistical notes

From the October 28 closing segment:

- unanswered questions should be taken to Discord office hours;
- Meta/team members will be present to answer participant questions;
- the session recording will be posted in Discord announcements;
- keep checking announcements because official clarifications may supersede our notes.

---

# 24. Submission-day checklist

Before recording/final submission:

- [ ] Re-read the current official rules.
- [ ] Re-open the actual submission form.
- [ ] Confirm deadline and timezone.
- [ ] Confirm repository is public.
- [ ] Confirm no secrets are present in tree or history.
- [ ] Confirm only hackathon-period work is presented as new.
- [ ] Confirm Meta model use is obvious and meaningful.
- [ ] Confirm demo is under the required duration.
- [ ] Confirm video is accessible without requesting permission.
- [ ] Confirm README explains setup and Meta tooling.
- [ ] Confirm all cited models/provider names are accurate.
- [ ] Confirm current validation tests pass.
- [ ] Confirm demo scenario works from a clean start.
- [ ] Confirm evidence/hypothesis state is visible.
- [ ] Confirm the model does not manufacture evidence.
- [ ] Confirm verification cannot be bypassed.
- [ ] Confirm failure/`needs_input` behavior is understandable.
- [ ] Confirm any open-weight bonus claim is genuinely supported.
- [ ] Confirm team/member fields are correct.
- [ ] Submit before the deadline, not at the last minute.

---

# 25. Current official references

These are useful starting points, but always prefer the latest version shown by Meta/Cerebral Valley.

- Meta Global AI Developer Hackathon event page:  
  https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon

- Meta Model API overview:  
  https://dev.meta.ai/docs/overview

- Meta Model documentation:  
  https://dev.meta.ai/docs/models

- Muse Code documentation:  
  https://dev.meta.ai/docs/muse-code

- Muse Code Contributor mode documentation:  
  https://dev.meta.ai/help/subscriptions/muse-code-contributor-mode

---

# 26. Final operating principle

When making a project decision, ask:

> Does this make the diagnostic loop more evidence-driven, more reliable, more visibly agentic, or easier for a judge to understand?

If the answer is no, it is probably not the next thing to build.

The strongest version of Hack the World is not the version with the most AI features.

It is the version where a judge can clearly see:

**the AI did not guess — it investigated.**
