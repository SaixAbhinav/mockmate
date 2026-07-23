# ADR 0023: The resume decides the domain; the picker becomes a label

Date: 2026-07-23 · Status: proposed

## Context

`SUPPORTED_DOMAINS = {"ml_genai"}` (`main.py:94`) rejects every Candidate who
isn't interviewing for an ML/GenAI role, at Session creation, before anything
else runs (`main.py:403`). A web developer with a good resume cannot start an
interview at all. That gate is the single biggest limit on who MockMate is for,
and ADR 0001 says the whole point is that strangers can try it.

[ADR 0015](0015-resume-grounded-warm-up.md) already built most of the way out
of this and said so: *"The domain picker's role shrinks to selecting the
fallback bank and labeling the Session."* Warm-up questions are already
generated from the resume in the ADR 0003 bank shape, so probe/clarify
grounding and the evaluator's rubric anchor work on them with zero new code.

**What `domain` actually controls today**, read off the code rather than
assumed — it is four unrelated things wearing one name:

1. **A gate** — the `SUPPORTED_DOMAINS` whitelist (`main.py:403`).
2. **An input to generation** — `_warm_up_user_turn` prepends
   `"Interview domain: {domain}"` (`providers.py:362`), and the system prompt
   tells the model to prefer resume items *"related to the domain"*
   (`providers.py:96`). So a Django-shaped resume still yields ML-flavoured
   questions.
3. **A filename** — the curated fallback is `load_bank(domain)` reading
   `questions/{domain}.yaml` (`questions.py:31`), which raises
   `QuestionBankError` when the file doesn't exist.
4. **A label** — stamped onto every question and the Session
   (`agent.py:82`, `:93`) and carried into the Evaluation payload
   (`evaluator.py:284`).

Only (4) is worth keeping as a Candidate-facing concept. (1) is the problem,
(2) is actively counterproductive, and (3) is the sharp edge: a free-form
domain has no YAML file behind it, so naively removing the whitelist breaks
ADR 0015's guarantee that **no Session ever fails to start**.

**This ADR is narrower than "reversing ADR 0003."**
[ADR 0003](0003-question-banks-open-source-curated.md) rejected
"LLM-generate everything" as the *bank* strategy, and that still holds — the
curated banks stay curated, and the DSA round stays 100% curated. ADR 0015
already took the exception for warm-up *content*. What's left to decide here is
only whether that exception extends from "which questions" to "which field the
questions are about." The coding round is unaffected.

## Decision

**The domain stops being a gate.** `SUPPORTED_DOMAINS` and the
`unsupported domain` 400 are deleted. `domain` becomes optional on
`CreateSessionRequest`.

**The resume names the field; no separate classification step.** The warm-up
generator already reads the whole resume, so it returns the field it inferred
as one extra key on the JSON it already produces (`"domain": string`, e.g.
`"web development"`). No second LLM call, no classifier, no taxonomy to
maintain. The generation prompt stops being told a domain and stops preferring
items "related to" one; it is told to write about the candidate's own primary
field as evidenced by the resume.

**The curated bank keeps a fixed name, decoupled from the label.** The
fallback draw becomes `plan_warm_up(FALLBACK_DOMAIN)` with
`FALLBACK_DOMAIN = "ml_genai"` — a module constant naming a file that is known
to exist, not a value derived from user input. `load_bank` never again receives
a string a Candidate can influence. Free-form domain labels therefore cannot
produce a `QuestionBankError`, and ADR 0015's no-Session-fails-to-start
guarantee survives unchanged.

**The domain becomes a display label with a known provenance.** It is a
free-form string on the Session, shown in the UI and carried into the
Evaluation exactly as today. When the warm-up came from the bank, the label is
the bank's own domain — which is honest, because those questions really are
ML/GenAI questions. This piggybacks on the existing `warm_up_source`
("resume" | "bank") field rather than adding a second provenance signal.

**The picker screen goes away**, replaced by the resume step. A visitor with no
resume still gets a Session — the curated ML/GenAI bank, labeled as such via
`warm_up_source: "bank"` — so ADR 0001's stranger is not locked out. This is
the most reversible part of the decision, and the natural seam for the
mandatory-resume step (with a bundled sample resume so visitors keep a
one-click way in) that is sequenced immediately after this one.

## Consequences

- **The coding round does not follow.** `plan_dsa` takes no domain and loads
  `dsa.yaml` unconditionally (`questions.py:168`), so a web developer gets a
  resume-grounded warm-up and then the same two Python DSA questions as
  everyone else. This ADR opens the front door without making the whole
  interview domain-appropriate; that mismatch becomes *more* visible, not
  less, and D4's system design round is the real answer to it.
- **Nothing outside ml_genai is human-vetted.** The whitelist was the last
  place a human stood between a Candidate and generated questions. What
  remains is the prompt's grounding constraint — never invent projects,
  employers, or skills not on the resume — which bounds *fabrication* but not
  *quality*. A weak question about a real project is now possible in a way it
  wasn't. Accepted deliberately: ADR 0015 already shipped that risk for
  ml_genai resumes, and this only widens the set of resumes it applies to.
- **The Evaluation's `domain` becomes uncontrolled vocabulary.** Two Sessions
  from near-identical resumes can be labeled "web development" and "full-stack
  engineering." Fine while `domain` is only displayed; it becomes a real
  problem the day anything *groups* by it — which is exactly what
  [ADR 0022](0022-weak-area-targeting.md)'s per-topic aggregation would want.
  Flagged here so 0022 decides it with this known, rather than discovering it.
  (Per-question `topic` has always been free-form from the generator, so 0022
  faces this regardless; this widens it by one field.)
- **The judge still never sees the resume** (ADR 0015's TPM argument is
  unchanged), so its only resume-derived grounding remains the generated
  `follow_up_hints`. Probing a domain nobody curated hints for leans harder on
  that one field.
- One less screen before the interview starts, and the existing seeded-draw
  tests for `plan_warm_up` keep working unchanged — the fallback path's
  behavior is identical, it just gets its argument from a constant.

## Alternatives considered

- **Explicit domain classification** (an LLM call, or a keyword pass, mapping
  the resume onto a fixed taxonomy). Rejected: it adds a call, a taxonomy to
  maintain, and a new failure mode, to produce a value whose only consumer is
  a label. The generator already has the resume in front of it.
- **Keep the picker as an optional "focus" hint** alongside the resume.
  Rejected for v1 as two sources of truth for one field — when the dropdown
  says ML and the resume says frontend, there is no good answer. Worth
  revisiting if real Candidates want to interview for a role they haven't
  worked in yet, which is a genuine use case this ADR does not serve.
- **A curated bank per domain before opening the gate.** That's ADR 0003's
  instinct, and it is the reason the whitelist exists. Rejected as the thing
  that keeps the gate shut indefinitely: banks are the slow, human part, and
  ADR 0015's machinery means a Candidate with a resume doesn't need one.
