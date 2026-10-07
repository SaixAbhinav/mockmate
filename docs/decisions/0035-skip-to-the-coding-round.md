# ADR 0035: The Candidate can skip to the coding round

Date: 2026-10-07 · Accepted: 2026-10-07 · Status: accepted · Amends [0012](0012-interview-structure-phased-dsa.md)'s fixed phase order

## Context

ADR 0012 fixed the order of a Session: intro, warm-up, coding round, wrap-up.
The only way into the coding round is to answer the intro and every warm-up
question, each of which may draw up to two follow-ups (ADR 0006). That is about
four spoken questions and up to twelve Turns before the first line of code.

That is right for a full mock interview and wrong for two real uses: a Candidate
who only wants to practise coding today, and anyone demonstrating the coding
round, the Watcher (0018) and the Runner (0016) without sitting through the
spoken half first.

## Decision

A Candidate can leave the spoken rounds at any point and go straight to the
first coding question.

- **A plain function, not a graph branch.** `agent.skip_to_coding` sits beside
  `submit_code`. A skip is the Candidate's choice, not an answer to judge, so
  the interview graph never runs and no LLM is called. The transition line
  ("Sure, skipping ahead to the coding round.") is fixed text, so the skip
  cannot fail on a Provider (0013).
- **What was said is kept; what was not is skipped.** The current question
  keeps any answers already given and is scored as normal if it had one. Every
  intro or warm-up question the Candidate never reached is closed out
  unanswered. The Evaluation already reports those as skipped, keeps them out
  of the averages and shows them in coverage (0011), so a skipped interview
  reads honestly without any new Evaluation shape.
- **One endpoint, the answer endpoint's response.**
  `POST /api/session/{id}/skip-to-code` returns the same `AnswerResponse` as
  `/answer`, `dsa` payload included, so the frontend opens the editor through
  the path it already uses. 409 once the Session is on a coding question or
  done.
- **Guarded in the UI.** The `Skip to code` button shows only during the intro
  and warm-up, and asks for confirmation first, because a skip cannot be undone.

## Consequences

- The coding round is reachable in one click, which also makes it practical to
  demo.
- Coverage, not a lower score, is what tells a skipped interview apart. The
  overall assessment sees the skipped questions as "never answered", the same
  as a Candidate who went silent.
- The phase order of 0012 still holds; a Session can now just leave it early.
  There is still no way back to the spoken rounds, and no skip within the
  coding round: a Submission remains the only way past a coding question
  (0017, 0019).

## Alternatives considered

- **Answer the remaining questions automatically from the frontend.** Rejected:
  one LLM call per skipped question, and junk answers in the transcript that
  the Evaluation would then try to score.
- **A `skip` route inside the interview graph.** Rejected: the graph exists to
  judge answers. A skip carries nothing to judge, and `submit_code` already set
  the precedent for state changes that are not answers.
- **A second start button that begins at the coding round.** Rejected for now:
  the in-interview button covers the same need (start, then skip at once) and
  also lets a Candidate leave a warm-up they have had enough of.
