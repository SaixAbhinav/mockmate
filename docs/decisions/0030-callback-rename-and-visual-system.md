# ADR 0030: Callback — rename, and a monochrome visual system

Date: 2026-08-04 · Status: accepted

## Context

The product shipped under the working title MockMate. The name is generic in a saturated
category — InterviewAI, Interviews.chat, Interviews by AI, FreeMockInterview, MockAI — and
"mock" frames a real, scored interview as a fake one.

The frontend's styling was never finished. `index.css` carried a full token system
inherited from a starter template, and `App.css` ignored all of it in favour of hardcoded
`#555` / `#888` / `#7ab`. `#root` still carried the template's `width: 1126px` and
`text-align: center`.

## Decision

**The product is Callback.** A callback is what you want after an interview, and
"callback interview" is standard recruiting language outside tech as well as a programming
term inside it. Availability was checked with three web searches and nothing surfaced in
this category; that is "nothing found", not a clearance.

Names rejected: **Open Interview** (taken twice in this exact category — openinterview.co.in
is voice-AI interviewing, plus openinterview.org and the phonetically identical
OpenIntervue); **Interview Loop** (taken — interviewloop.co is an AI mock interviewer for
technical interviews); **Interview Aloud / Bench / Room** (all unclaimed, all forgettable
inside the field above).

**The rename is display-only.** User-visible text changes. The identifier `mockmate`
survives as the Terraform name prefix, the GitHub repo slug, the CI badge URL, the Docker
image name, the Render service name, and the `MOCKMATE_*` env vars. Those names derive the
S3 bucket, ECR repository, DynamoDB table, Lambda and SSM parameters, and renaming them is
a destroy-and-recreate against live infrastructure that no user would ever see. If it is
ever done it gets its own PR and its own `terraform apply`.

**The interface is monochrome, with colour reserved for state.** White on black, no brand
hue. The only colour in the application is `#3fb950` for passing tests and `#e5484d` for
failing ones and for error states more broadly (the same red also borders the error
banner), plus `#d29922` for transient status. This is functional before it is
aesthetic: the one place colour carries real information is the test report in the coding
round (ADR 0016/0017), and a brand accent elsewhere competes with it.

Illustration is monoline white line art, front of house only. The live interview and
coding surfaces carry no illustration — a busy background behind a live editor works
against the task the Candidate is being asked to do.

## Consequences

- Two names now exist for one system. Anyone reading `infra/` will see `mockmate` and must
  not "fix" it. This ADR is the reason it is not a bug.
- No light theme ships. The tokens are structured so one can be added as a single block.
- Any future accent colour has to justify itself against the pass/fail signal it dilutes.
- The design system is enforced only by review; there is no lint rule preventing a
  hardcoded hex from creeping back into `App.css`.
