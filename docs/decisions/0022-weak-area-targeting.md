# ADR 0022: Weak-area targeting — deferred for v1

Date: 2026-07-21 · Decided: 2026-07-24 · Status: deferred

## Decision

Deferred for v1 — not built now. The feature has no users to prove its value
(the analysis below admits a v2 would depend on "real usage data on whether
biased selection alone feels valuable"), and it cannot exist without cross-
Session identity. That identity forces either the full accounts day
([ADR 0009](0009-accounts-and-data-retention.md)) or a per-device model that
directly contradicts 0009's accepted decision — *"auth is email/OAuth accounts
rather than anonymous device ids."* Paying that cost for a speculative feature
nobody has asked for is over-engineering. The analysis is kept intact below;
revisit when real usage demands weak-area targeting and the accounts day exists
(or is worth doing) for its own reasons.

## Context

The README has promised this since before any of the interview logic existed:
*"(soon) scores you against rubrics and targets your weak areas."* Nothing
currently implements the second half. An Evaluation today is a terminal
artifact — `GET /api/session/{id}/evaluation` produces a scored report and
nothing reads it back into a future Session (ADR 0011).

Three ADRs already anticipated this day without committing to it:

- **ADR 0005** pre-announced Chroma as the vector DB, "for question banks +
  uploaded resumes" — not explicitly for weak-area targeting, but it's the
  only unclaimed reason a vector DB was on the original stack.
- **ADR 0007** decided Sessions are in-memory *for now*, with persistence as
  the designed-for upgrade path. [ADR 0021](0021-session-store-interface.md)
  just built that seam (`SessionStore`), so the blocker ADR 0007 anticipated
  is gone.
- **ADR 0011** explicitly designed the evaluator's output for this: per-
  question Scores carry `topic` alongside Dimension scores, Coverage exists
  specifically so an unanswered question reads as "unattempted," not as a
  false pass — and its Consequences section says outright, *"weak-area
  targeting slots in later without a rewrite."*

**What's new here, checked directly against the code rather than assumed:**
every curated Question already carries a `topic` string (`ml_genai.yaml`:
`bias-variance`, `fundamentals`, etc. — `Question.topic` in
`backend/app/questions.py`), and the evaluator's per-question record already
threads that `topic` through to the Evaluation payload (`evaluator.py`,
building each unit's record). **The data a weak-area signal needs already
exists in every Evaluation produced today.** Nothing about scoring needs to
change; the gap is entirely about *persisting it past one Session* and then
*acting on it in the next one*.

This also corrects an error in this repo's working plan (`2026-07-21.plan.md`,
now fixed there too): an earlier draft claimed this feature contradicts ADR
0007. It doesn't — 0007 explicitly designed for this swap. The real
prerequisite was the missing `SessionStore` interface, which ADR 0021 supplies.

## Open questions

### 1. What is a "weak area," concretely?

Three candidates, in order of how much they cost:

- **(a) Per-topic Dimension average.** For a Candidate, across however many
  Sessions they've done, average `depth`/`correctness`/`clarity` grouped by
  `topic`. Uses data that already exists in every Evaluation. Zero new scoring
  logic, zero new LLM calls.
- **(b) Per-topic Coverage.** A topic where questions keep going unanswered
  (`answered: false`) is a different signal than one that's answered but
  scored low — ADR 0011 built Coverage precisely so these don't get
  conflated. A "weak area" for v1 should probably be *either* signal, not
  just Dimension averages, or a Candidate who dodges a topic entirely reads as
  having no weakness there.
- **(c) Embedded topic clusters.** Cluster topics by semantic similarity
  (e.g. "bias-variance" and "overfitting" are related) so weakness in one
  informs targeting of the other, even across differently-worded questions.
  This is what would need Chroma/sentence-transformers.

**Recommendation: (a) + (b) for v1, defer (c).** The curated `topic` tags
are already a controlled vocabulary — a human wrote them, and there are only
as many as the bank has entries for. Clustering solves a problem this app
doesn't have yet (a sprawling, uncurated bank where topics need to be
discovered rather than read off the YAML). Revisit (c) if question banks grow
large enough that hand-curated topics stop being enough signal on their own.

### 2. Where does this persist, and does it force ADR 0009?

**Yes, unavoidably**, and this is the sharpest edge of the whole feature. ADR
0009 was explicit: Sessions stay anonymous for now, and *"persisting
strangers' personal data indefinitely without a way to remove it is the kind
of thing that's awkward to retrofit."* Weak-area targeting only means
something if the same Candidate is recognized across Sessions — which
requires exactly the identity ADR 0009 deferred.

This is not a detail to settle inside this ADR; it's the reason this ADR
can't authorize implementation on its own. Two sub-options if the direction
is approved:

- **(a) Full accounts now**, per ADR 0009's shape (email/OAuth, deletion
  included in the same day). Correct long-term, but ADR 0009 already flagged
  this as bigger than it sounds — deletion "touches every place resume/
  history data is stored."
- **(b) A narrower persistent-but-anonymous identity** — a device-bound or
  locally-stored id, no login, weak areas tracked against *that* id, framed
  honestly as "your last N sessions on this device" rather than "your
  account." Smaller, but is arguably a second identity model running
  alongside whatever ADR 0009 eventually builds, which is its own kind of
  debt.

**Recommendation: (b) as a deliberately small first step, with the
understanding that it either gets folded into ADR 0009's eventual accounts
work or is explicitly superseded by it.** Full accounts is a correct
long-term answer but a disproportionate gate in front of a first version of
this feature. This trade-off is the one most worth pushing back on — it's a
real product decision, not a technical one.

### 3. Does targeting change selection or generation?

- **Selection** — bias `plan_warm_up`'s draw (`backend/app/questions.py`,
  currently `rng.sample(bank, 3)`, uniform) toward topics with a low score or
  low Coverage for this Candidate. Small, contained change: one function,
  same signature, same random-seed testability.
- **Generation** — have the Interviewer probe harder specifically on known-
  weak topics mid-Session (an addition to the judge/probe prompt in
  `providers.py`). Bigger: touches prompt design, and risks the Session
  feeling like it's "testing the sore spot" rather than assessing fairly.

**Recommendation: selection only, for v1.** It's the cheaper half, it's
already isolated behind a pure function with existing test coverage, and it
delivers the README's promise ("targets your weak areas") without touching
prompt behavior that's already been tuned across ADRs 0006/0011/0013.
Generation-side probing is a legitimate v2, once there's real usage data on
whether biased selection alone feels valuable.

### 4. Is an embedding store needed for v1?

**No.** Per-topic Dimension averages and Coverage are plain aggregation over
existing Evaluation data — a `dict[topic, DimensionAverages]` per Candidate
id, no vector search involved. Chroma only becomes relevant if question 1
resolves toward (c) — semantic topic clustering — which this ADR recommends
deferring. Flagging this explicitly because the README pre-announces Chroma:
**v1 of this feature would add no new dependency at all.**

## Recommendation (summary)

1. Weak area = per-topic Dimension average **and** per-topic Coverage,
   computed from data the evaluator already produces (Q1: a+b).
2. Persist against a narrow, anonymous per-device identity — not full ADR
   0009 accounts — as a deliberately small first step (Q2: b), flagged as the
   trade-off most worth a second opinion.
3. Bias question **selection** only; leave probe/clarify generation untouched
   for v1 (Q3: selection).
4. No new dependency — Chroma stays deferred until/unless topic clustering is
   actually needed (Q4: no).

## Consequences if accepted as recommended

- First real persistent (if narrow) identity in the app — a bigger step than
  it looks, since every future feature touching "the Candidate" now has a
  place to hang data off of.
- No new dependency, no change to prompts, no change to scoring — the whole
  feature is additive aggregation plus one selection-function edit.
- Defers the harder, more valuable version (semantic clustering, generation-
  side probing, full accounts) rather than solving them speculatively.
- Does not yet answer deletion/retention mechanics for the narrow identity —
  that has to be specified before implementation, not left implicit the way
  ADR 0009 warned against.

## Status

Deferred for v1 (decided 2026-07-24). The grilling that closed this out did not
resolve question 2 by choosing accounts vs. per-device identity — it rejected
the premise that the feature earns either one yet. See the Decision section at
the top.
