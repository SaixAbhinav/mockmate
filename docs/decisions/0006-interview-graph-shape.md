# ADR 0006: Interview graph shape — named phases with a Probe/Clarify follow-up budget

Date: 2026-07-14 · Status: accepted

## Context

The bare chat loop (`/api/turn`) has no notion of a session, question plan, or
ending. It needs replacing with something that can run a real interview:
pick a domain, work through questions, react to answer quality, and stop.
Considered alternatives: a single "router" node deciding everything each
turn, or a free-form tool-using agent. Both are more flexible but harder to
test with no test suite yet (Day 1 debt).

## Decision

`plan_session → ask_question → (wait for answer) → judge_answer_depth →`
one of:
- **Probe** — same-topic follow-up, answer was on-topic but shallow.
- **Clarify** — follow-up when the answer was off-topic or showed the
  candidate misunderstood the question. Distinct trigger from Probe, but
  shares the same follow-up budget (2 per question, not 2 Probes + separate
  Clarify attempts).
- **next_question** / **wrap_up** — advance or end.

If the budget runs out while still on Clarify (candidate never actually
answered), the question is marked `answered: false` in session state before
advancing, distinguishing "gave up on a shallow answer" from "never got a
real answer" for a future evaluator agent.

`plan_session` builds a fixed-length queue: a seeded random draw of N (~6–8)
questions from the domain bank, sorted easy→hard. Fixed length gives the
progress UI ("question 3 of 8") a denominator; seeding keeps tests
deterministic while sessions still vary.

**One combined LLM call per answer**, not two. `judge_answer_depth` and the
spoken reply are produced together via one structured (JSON) call returning
the classification (exactly one of **probe / clarify / advance**, plus the
`answered` flag) and the reply text — halving round-trips to keep latency near
the Day-1 baseline. On **probe/clarify** the returned text is the full spoken
follow-up. On **advance** the LLM returns only a one-sentence reaction; the
backend then appends the next question *verbatim from the YAML bank* (ADR
0008), so curated wording is never paraphrased by the model.

**The LLM never decides to end.** `wrap_up` is graph-triggered, not a judge
output: when `advance` is chosen and the question queue is now empty, the
conditional edge routes to `wrap_up` instead of `ask_question`. Session length
is therefore deterministic (the N questions from `plan_session`). `wrap_up`
then makes a *separate* structured call in "wrap-up mode" that returns a brief
closing remark (no scoring — the evaluator agent is Day 3+); phase becomes
`done`. So the judge classification has three values, and `done` is a phase,
not something the model chooses.

This single structured method **replaces** the walking skeleton's
`LLMProvider.chat() -> str`. Since `/api/turn` is deleted in the same PR,
`chat()` has no remaining caller and is removed; the interview graph is the
only LLM caller and it only needs the structured method. `ScriptedProvider`
implements it by always returning `advance` with a generic reaction (walks
the queue, never probes), preserving the zero-setup demo (ADR 0002) and
doubling as the fake provider for graph tests.

**Robustness.** If the structured call returns malformed JSON or an unknown
classification, the graph defaults to `advance` with a neutral reaction (and
logs it) rather than crashing the turn — worst case is a missed probe.

## Consequences

- Named phases are independently testable (graph transitions, probe/clarify
  cap, `answered` flag) — no test debt carried into Day 3. Test targets
  explicitly include the clarify path, the shared probe+clarify budget
  (capped at 2 combined), and `answered: false` on budget-exhausted-unresolved
  — these are today's new decisions and the most likely to silently regress.
- One shared counter, not two, keeps state minimal.
- `answered: false` is written now even though nothing reads it yet — it's
  cheap to add at the point of decision and expensive to reconstruct later
  from raw transcripts.
- Known deferred debt: abandoned in-memory sessions are not cleaned up (leak
  until restart) — acceptable at demo traffic, addressed with the SQLite/
  accounts migration (ADR 0007/0009). Turn latency is measured and recorded,
  not held to a hard limit for Day 2.
