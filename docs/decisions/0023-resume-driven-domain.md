# ADR 0023: The resume decides the domain; the picker becomes a label

Date: 2026-07-23 · Status: accepted

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
`unsupported domain` 400 are deleted.

**Domain becomes a derived output, not an input** — the `domain` field is
removed from `CreateSessionRequest` entirely, not merely made optional. Every
job it did is going elsewhere: the gate is gone, the fallback bank uses a
constant, the prompt stops being told a domain, and the label comes back from
the generator. A field with no remaining consumer is a lie in the API shape,
and an ignored-but-accepted field invites a future change to "helpfully" wire
it back up to something. The Candidate loses the ability to request an
interview in a field their resume doesn't show; that use case is real but not
one this ADR serves.

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

**The fallback is disclosed before the Session is created, not after.** When
generation returns nothing usable — an empty list, a `ProviderError`, or the
keyless `ScriptedProvider`, which returns `[]` unconditionally
(`providers.py:843`) — the Candidate is told what they are about to get and
chooses whether to proceed: *"We couldn't tailor this to your resume. We can
run a general ML/GenAI interview instead."* Start or cancel.

This tightens ADR 0015 rather than contradicting it. 0015 required that the
fallback be *labeled, never silent*, and it is — but the notice renders on the
interview screen after the Session already exists (`App.jsx:408`), and its copy
only says grounding is unavailable. That was sufficient while the Candidate had
picked `ml_genai` from a dropdown themselves: the only news was "not
personalised." With the picker gone nobody chose anything, so the same sentence
understates it — the news becomes "this is an ML/GenAI interview and you are a
frontend developer." Disclosure has to move ahead of the twenty-minute
commitment.

**The domain becomes a display label with a known provenance.** It is a
free-form string on the Session, shown in the UI and carried into the
Evaluation exactly as today. When the warm-up came from the bank, the label is
the bank's own domain — honest, because those questions really are ML/GenAI
questions. This piggybacks on the existing `warm_up_source`
("resume" | "bank") field rather than adding a second provenance signal.

**The pre-Session screen survives; it stops asking about subject matter.** An
earlier draft of this ADR claimed the picker screen disappears. It doesn't. A
Candidate should still choose the *shape* of their interview — algorithms
today, or a conversation about their projects — and no resume can answer that,
because it is a preference rather than a fact. That is a different axis from
the one this ADR removes: **subject** is derived from the resume, **shape** is
chosen by the Candidate. The shape selector (a Track) is deliberately left to
its own ADR; this one only establishes that removing the domain picker does not
mean removing the screen.

## Consequences

- **The algorithmic round stays universal, deliberately.** `plan_dsa` takes no
  domain and loads `dsa.yaml` unconditionally (`questions.py:168`), so every
  Candidate gets the same two coding questions. This is not treated as a
  defect: data-structures rounds are a normal part of interviews well outside
  ML, and a frontend developer asked to implement `is_palindrome` is having an
  ordinary interview experience, not a mismatched one.
- **Python-only is the real limitation, and it is separate.** The Runner
  executes Python, the starter code and signatures are Python, and the
  Evaluation scores `code_quality` on Python. A Candidate who writes TypeScript
  all day is demonstrating algorithmic thinking in a second language. No amount
  of resume grounding or bank expansion fixes this — it needs a second Runner.
  Accepted and deferred: this is a student project, and a JS runner is purely
  additive whenever demand appears.
- **Correctness scoring gets weaker for every non-ML Candidate, and this ADR
  does not fix it.** `EVALUATE_SYSTEM_PROMPT` scores *"is what they said
  accurate?"* (`providers.py:46`), but resume-grounded questions are about the
  Candidate's own private projects, where no external ground truth exists. The
  weakness is **pre-existing** — ADR 0015 shipped it — but today those
  questions are at least about ML work, where the model has strong priors.
  Widening the domain widens the gap. ADR 0015 excluded the intro from the
  Evaluation for exactly this reason (*"scoring 'tell me about yourself' on
  correctness 1–5 is meaningless"*), and that argument does not obviously stop
  at the intro. The answer is to give the judge the resume as ground truth —
  ADR 0015's own named upgrade path — which is a large enough change, with real
  per-turn token and fairness consequences, to need its own ADR. Named here,
  not fixed here.
- **The Evaluation's `domain` becomes uncontrolled vocabulary.** Two Sessions
  from near-identical resumes can be labeled "web development" and "full-stack
  engineering." Fine while `domain` is only displayed; it becomes a real
  problem the day anything *groups* by it — which is what
  [ADR 0022](0022-weak-area-targeting.md)'s per-topic aggregation would want.
  (Per-question `topic` has always been free-form from the generator, so 0022
  faces this regardless; this widens it by one field.)
- **The judge still never sees the resume** (ADR 0015's TPM argument is
  unchanged), so its only resume-derived grounding remains the generated
  `follow_up_hints`. Probing a domain nobody curated hints for leans harder on
  that one field.
- **Judge, wrap-up, and evaluator prompts need no changes.** Checked directly:
  none of them contain ML-specific language (`providers.py:22`, `:38`, `:46`).
  Domain-neutrality was already there; this ADR just starts relying on it.
- **A wide, mechanical test diff.** Roughly twenty call sites in
  `test_main.py` pass `{"domain": "ml_genai"}` and become `json={}`, and the
  unsupported-domain test is deleted. Small behaviour change, broad diff — an
  argument for landing this before other work touches Session creation.
- The existing seeded-draw tests for `plan_warm_up` keep working unchanged; the
  fallback path behaves identically, it just gets its argument from a constant.

## Alternatives considered

- **Explicit domain classification** (an LLM call, or a keyword pass, mapping
  the resume onto a fixed taxonomy). Rejected: it adds a call, a taxonomy to
  maintain, and a new failure mode, to produce a value whose only consumer is
  a label. The generator already has the resume in front of it.
- **Keep `domain` on the request as an optional "focus" hint.** Rejected as two
  sources of truth for one field — when the request says ML and the resume says
  frontend, there is no good answer. This is *not* an argument against letting
  the Candidate choose anything: choosing the Track (shape) is orthogonal and
  is expected to land next.
- **Improve the existing fallback notice instead of adding an interstitial.**
  Cheaper — one string change — but the Candidate still finds out after
  committing their time, which is the one thing the old 400 did better.
- **A curated bank per domain before opening the gate.** That's ADR 0003's
  instinct, and it is the reason the whitelist exists. Rejected as the thing
  that keeps the gate shut indefinitely: banks are the slow, human part, and
  ADR 0015's machinery means a Candidate with a resume doesn't need one.
