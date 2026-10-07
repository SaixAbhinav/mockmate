# Skip to Code, and a sample scorecard on the landing page

Date: 2026-10-07 · Status: approved

Two small, independent features shipped together in one PR.

## 1. Skip to Code

A Candidate can leave the spoken rounds (intro, warm-up) at any point and go
straight to the coding round. Recorded as ADR 0035.

### Backend

- `agent.skip_to_coding(state) -> InterviewState`, a plain function beside
  `submit_code` (a skip is not a judged answer, so it does not run through the
  graph). No LLM call.
  - The current question is closed out. It counts as answered only if the
    Candidate has given at least one answer to it (`current_answers` non-empty)
    and the judge had not marked it unanswered; otherwise it is recorded as
    not answered, which the Evaluation shows as skipped.
  - Every remaining non-coding question in the queue is closed out as not
    answered, with no answers.
  - The first coding question becomes current; the rest of the coding queue is
    untouched. `follow_up_count`, `current_answers` and `current_answered` reset
    as for any new question.
  - The reply is `SKIP_REMARK` ("Sure, let's go straight to the coding round.")
    joined to the coding question, and it is appended to the transcript as one
    assistant turn. Phase becomes `asking`.
- `POST /api/session/{id}/skip-to-code`, body `{voice}`, response
  `AnswerResponse` (same shape as `/answer`, including the `dsa` payload).
  - 404 for an unknown Session.
  - 409 when the Session is done or the current question is already a coding
    question.

### Frontend

- `useSession.skipToCode()` posts to the endpoint and applies the response with
  the existing `applyProgress`, so the editor opens through the normal path.
- A `Skip to code →` button in the top bar, rendered only while `stage` is
  `intro` or `warm_up` and the Session is not done. Disabled unless `status` is
  `idle` or `speaking`.
- A `window.confirm` guards it: "Skip the remaining warm-up questions? They'll
  show as skipped in your Evaluation." Cancel does nothing.

### Tests

- Agent: unanswered current question becomes skipped; a partly answered one is
  kept; leftover warm-up questions are skipped; coding queue intact; reply and
  transcript.
- Endpoint: 200 with a `dsa` payload; 409 on a coding question; 404 unknown;
  the Evaluation afterwards lists the skipped questions.
- Frontend: button only in intro/warm-up; confirm then POST; cancel sends
  nothing.

## 2. Sample scorecard on the landing page

- A section after the phases list, "What you walk away with", showing the real
  `<Evaluation>` component rendered from fixed sample data in
  `landing/sampleEvaluation.js`, captioned "Example scorecard · sample data".
- Sample: an assessment, 2 strengths, 2 improvements, 2 warm-up questions from
  the ML/GenAI bank with scores, 2 coding questions (6/6 and 4/6 tests passing),
  1 hint used.
- The card sits in a framed panel with a capped height and a bottom fade.
- The Evaluation's rules move from `App.css` to `components/Evaluation.css`,
  imported by the component, so the landing page gets them without the app's
  stylesheet. The app's look is unchanged.
- Tests: the landing page renders the sample scorecard and its caption; the
  sample has every key `EvaluationResponse` returns.
