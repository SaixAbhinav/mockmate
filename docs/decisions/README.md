# Decision index

The single roll-up of every architectural decision in MockMate — what's decided,
what's still open, and where the open ones stand. Each row's `Status` mirrors the
`Status:` line inside that ADR; this table is the at-a-glance view, the ADR file
is the detail.

**When you change an ADR's status, update its row here in the same commit.** An
index that drifts from the ADRs is worse than no index.

## Status legend

- **accepted** — decided and in effect.
- **proposed** — written to be argued with; not yet in effect. May or may not have code.
- **amended / superseded** — still readable for history, but another ADR now governs part or all of it.
- **draft (uncommitted)** — exists as a file but not yet on `main`.

## Accepted decisions

| # | Title | Status |
|---|---|---|
| [0001](0001-multi-user-not-personal-tool.md) | Multi-user product, not a personal tool | accepted |
| [0002](0002-llm-provider-free-tier-with-fallback.md) | LLM provider — hosted free tier primary, pluggable fallback | accepted |
| [0003](0003-question-banks-open-source-curated.md) | Question banks — open-source seeds + curated expansion | accepted |
| [0004](0004-voice-stack-browser-stt-edge-tts.md) | Voice stack — browser Web Speech (STT) + Edge-TTS | amended · STT half superseded by [0010](0010-stt-groq-whisper-primary.md) |
| [0005](0005-stack-react-fastapi-langgraph-chroma.md) | Stack — React+Vite / FastAPI / LangGraph / Chroma | accepted |
| [0006](0006-interview-graph-shape.md) | Interview graph shape — phases + Probe/Clarify budget | accepted |
| [0007](0007-session-state-in-memory.md) | Session state — in-memory behind an interface | accepted |
| [0008](0008-question-source-curated-yaml.md) | Question source for v1 — curated YAML, LLM only for follow-ups | accepted |
| [0009](0009-accounts-and-data-retention.md) | Real accounts with deletion, as a separate later day | accepted (not yet built) |
| [0010](0010-stt-groq-whisper-primary.md) | STT — Groq Whisper primary, browser as no-key fallback | accepted · supersedes STT half of [0004](0004-voice-stack-browser-stt-edge-tts.md) |
| [0011](0011-evaluator-agent-rubric-scoring.md) | Evaluator agent — batch fan-out rubric scoring | accepted |
| [0012](0012-interview-structure-phased-dsa.md) | Interview structure — phased session, resume warm-up + DSA | accepted |
| [0013](0013-provider-failures-malformed-vs-unavailable.md) | Provider failures — malformed vs unavailable | accepted |
| [0014](0014-cross-provider-failover.md) | Cross-provider failover — Groq primary, Gemini fallback | accepted |
| [0015](0015-resume-grounded-warm-up.md) | Resume-grounded warm-up on a staged question queue | accepted |
| [0016](0016-dsa-bank-and-sandboxed-runner.md) | DSA part 1 — extended bank + sandboxed runner | accepted |
| [0017](0017-dsa-submit-flow.md) | DSA part 2 — submit, react, discuss through the graph | accepted |
| [0018](0018-watching-interviewer-check-ins.md) | Watching interviewer part 1 — snapshots + check-in policy | accepted |
| [0019](0019-voice-live-while-coding.md) | Watching interviewer part 2 — voice stays live while coding | accepted |
| [0020](0020-dsa-round-scoring.md) | DSA-round scoring — measured facts, judged quality | accepted |
| [0021](0021-session-store-interface.md) | Session store — the interface 0007 promised | accepted |

## Open — decided direction, not yet closed out

| # | Title | Status | Where it stands |
|---|---|---|---|
| [0023](0023-resume-driven-domain.md) | The résumé decides the domain | accepted | ADR in PR #22; implementation in PR #24 (9 commits, 209 tests green). Not yet merged. |
| [0024](0024-offline-question-generation.md) | Generate banks offline, gate by machine, review by hand | proposed | ADR in PR #23. No code. Awaiting decision. |
| [0022](0022-weak-area-targeting.md) | Weak-area targeting | proposed · draft (uncommitted) | Draft file on disk, not committed. Blocked on one product call: full accounts (0009) vs. a narrow per-device identity. |

## Not yet ADRs — parked threads

Decisions taken in discussion (the 2026-07-23 grilling of 0023) that each need
their own ADR before any code. Recorded so they aren't lost.

- **Track selector** — let the Candidate choose the *shape* of the interview
  (Standard / Project-based / System design), distinct from Domain (the
  *subject*, which the résumé decides). Absorbs the old "selectable length"
  idea and reframes the system-design round as one Track among several.
- **Résumé-aware judge** — give the interviewer a compact *résumé digest* as
  ground truth so it can tell when a claimed project can't be explained.
  Reverses 0015's "the judge never sees the résumé"; carries real token-budget
  and fairness questions.

## The roadmap these came from

Feature-level sequencing (D1–D4) and per-thread progress live in the root
`*.plan.md` files, which are gitignored working notes. This index tracks
*decisions*; those track *work*.
