# Callback — UI/UX redesign

Design spec, 2026-08-04. Covers the rename from MockMate to Callback, a visual system,
a component/hook split of the frontend, and a rebuilt coding round.

---

## Why

The frontend is one 768-line `App.jsx` and a 247-line `App.css`. Three concrete problems:

1. **The styling is unfinished.** `index.css` defines a full token system — `--accent`,
   `--border`, `--text-h`, light and dark pairs — and `App.css` ignores all of it in
   favour of hardcoded `#555`, `#888`, `#7ab`. `#root` still carries Vite template
   leftovers (`width: 1126px`, `text-align: center`).
2. **The coding round doesn't fit.** Everything lives in one 720px column, so a 220px
   editor is wedged between a scrolling transcript and the composer. You cannot see your
   code and the interviewer's question at the same time — which is the entire premise of
   the watching interviewer (ADR 0018).
3. **The name undersells and doesn't stick.** "MockMate" is generic in a saturated
   category, and "mock" frames a real, scored interview as a fake one.

## Goals

- A visual system the whole app actually uses, defined once.
- A coding round where code and conversation are visible together.
- A frontend split into units small enough to reason about and test.
- A name and identity worth putting on a portfolio.

## Non-goals

- No change to interview logic, the graph, scoring, or any ADR-recorded behaviour.
- No renaming of AWS resources or the GitHub repo slug (see below).
- No light theme in this work. Tokens are structured so one can be added later.
- No new frontend framework, router, or CSS library.

---

## 1. Name and identity

**The product is Callback.** Lockup: `Callback — voice interview practice, in the open`.

A callback is what you want after an interview, so the word is already interview
vocabulary — including outside tech, where "callback interview" is standard recruiting
language. It is also a programming term, so it lands twice with the audience. Availability
was checked with three web searches: no interview-preparation product surfaced under the
name. This is "nothing found", not an exhaustive clearance. Because `callback` is a
ubiquitous programming word, organic search will never belong to this project; the header
lockup, README and OG card carry the category instead.

Names rejected, and why, so this is not relitigated:

| Name | Reason |
| --- | --- |
| Open Interview | Taken twice, both in this exact category — openinterview.co.in (voice-AI interviewing) and openinterview.org, plus phonetically identical OpenIntervue. |
| Interview Loop | Taken — interviewloop.co is an AI mock interviewer for technical interviews. |
| Interview Aloud / Bench / Room | All unclaimed, all forgettable inside a field of InterviewAI, Interviews.chat, Interviews by AI, FreeMockInterview. |

**The rename is display-only.** `mockmate` appears in ~30 tracked files. The user-visible
ones (README, ADRs, `App.jsx`, docstrings, page title) change. The Terraform name prefix
in `infra/*.tf` and the GitHub repo slug **stay `mockmate`**, because those names derive
the S3 bucket, ECR repository, DynamoDB table, Lambda and SSM parameters, and renaming
them is a destroy-and-recreate against live infrastructure that buys nothing a user can
see. ADR 0030 records this split as deliberate. If the infrastructure is renamed later it
gets its own PR and its own `terraform apply`.

---

## 2. Visual system

**Monochrome, with colour reserved for state.** The interface is white-on-black. There is
no brand hue. The only colour anywhere in the application is green for passing tests and
red for failing ones. This is a functional decision as much as an aesthetic one: the one
moment in the product where colour carries real information is the test report in the
coding round, and an accent hue elsewhere competes with it.

### Tokens

Replaces the current `index.css` block entirely. Dark only; `color-scheme: dark`.

```
--bg:            #0c0c0c   ground
--surface:       #151515   cards, rails, composer
--surface-2:     #1c1c1c   code blocks, inset wells
--border:        #262626   hairlines
--border-strong: #3a3a3a   focus, hover
--text:          #fafafa   primary
--text-muted:    #8a8a8a   secondary, labels
--text-dim:      #5c5c5c   metadata, disabled
--pass:          #3fb950
--fail:          #e5484d
--pending:       #d29922   transcribing / thinking status only
```

Spacing scale `4 8 12 16 24 32 48 64`, replacing the eleven ad-hoc `rem` values in the
current CSS. Radii: `2px` default, `4px` for code surfaces. No pills, no glass, no
gradients, no glow.

### Type

- **Display** (wordmark, hero, `h1`/`h2`): system serif stack —
  `'Iowan Old Style', Georgia, 'Times New Roman', serif`. No web font is downloaded, so
  there is no font-loading work in the CloudFront/S3 path (ADR 0029). Swapping in a
  self-hosted display face later is a one-line token change.
- **Body and UI**: the existing system sans stack.
- **Code and small-caps labels**: the existing mono stack.

Speaker labels are uppercase mono at `0.7rem` with `1.4px` tracking.

### Line art

Illustration is monoline, white, `1.1px` stroke at a 40px artboard, round caps and joins,
no fill. It appears **front of house only** — the landing hero and section markers. The
live interview and coding surfaces carry no illustration; their depth comes from the
surface step and the speaker rule alone. A busy background behind a live coding editor is
hostile to the task.

### Transcript treatment

No chat bubbles. Each turn is a small-caps speaker label above the text, with a 2px rule
down the left edge — solid `--text` for the interviewer, `--border` for the candidate.
The same component renders the coding round's narrow rail, so the two screens share one
idea rather than inventing two.

---

## 3. Structure

`App.jsx` becomes a shell that owns screen routing and composes the pieces below. Nothing
here invents behaviour; it is extraction of what already exists.

### Hooks — `src/hooks/`

| Hook | Owns |
| --- | --- |
| `useSession` | Session lifecycle, history, phase/stage/question counters, `applyProgress`, `sendTranscript`, resume upload and its supersede token. |
| `useRecorder` | `getUserMedia`, the peak-amplitude speech gate, the minimum-duration guard, transcription. |
| `useDsaRound` | Code state, run and submit, the snapshot debounce and the check-in poll (ADRs 0018/0019). |
| `useEvaluation` | The scoring fetch and its abort handling. |

### Components — `src/components/`

| Component | Renders |
| --- | --- |
| `StartScreen` | Hero, landing copy, résumé upload, fallback offer, waking notice. |
| `Transcript` | The speaker-ruled message list. Takes `variant: 'full' \| 'rail'`. |
| `Composer` | Text input, send, mic button, recording state. |
| `CodingWorkspace` | Pinned question, signature, CodeMirror, run/submit, results table. |
| `InterviewerRail` | Pinned latest remark plus collapsed history disclosure. |
| `Evaluation` | The scorecard. |

Each has one job and one obvious test seam, and no file stays large enough that editing it
means re-reading 768 lines.

---

## 4. Screens

### Start screen

Keeps its ADR 0025 purpose — reading copy gives the sleeping container time to wake. Gains
the line-art hero, the serif headline, and the lockup. The raw `<input type="file">`
becomes a drop-target card with three states: empty, uploading, ready (filename with
change/remove). The waking notice moves from a detached italic aside to inline status on
the Start button, attached to the thing it is actually blocking.

### Interview screen — intro and warm-up

Single centred column, max 720px. Speaker-ruled transcript. Status collapses from three
separate spans into one dot-and-word indicator; measured latency moves behind its `title`
rather than occupying permanent chrome. Progress (`warm-up · question 2 of 5 · probing`)
becomes a slim bar under the header.

### Coding round

The page widens from 720px to 1140px when a `dsa` payload arrives and narrows back on
submit. Editor takes roughly two thirds, interviewer rail one third.

Above the editor, pinned: **the question text**, then the signature in mono. The rail shows
only the latest interviewer remark in a ruled card, with `▸ N earlier messages` collapsed
beneath it. The composer sits under the editor, so thinking aloud does not require crossing
the screen. Below 900px the panes stack, question first.

**This needs one backend change.** `DsaPayload` (`backend/app/main.py:166`) carries
`function_name`, `signature`, `starter_code`, `test_cases` — no problem statement. The text
exists only as the spoken assistant turn in chat history. The bank already stores it as
`question:` in `dsa.yaml`, so a `prompt: str` field is a small, honest addition rather than
a frontend workaround.

The question also **stays in the transcript**. It is a real spoken turn, and removing it
would leave a hole in the interview record. The duplication is accepted deliberately.

### Run results

The current flat list of failures becomes a summary line (`7 of 8 passed`, coloured
`--pass`/`--fail`) with failures in a compact three-column table — args, expected, got.
Three `<code>` runs jammed into a sentence is unreadable at a glance.

### Evaluation

Five-point scores become small labelled bars rather than pill chips; a 1–5 scale reads
badly as text. Per-question sections become collapsible, since five questions plus two
coding questions is a long scroll.

### Errors

Move from a `<p>` at page bottom — below the fold during the coding round — to a
dismissible banner beneath the header. Every error path in this app is one the candidate is
expected to act on: retry, allow the microphone, type instead.

---

## 5. Testing

The frontend has no test setup today. Per the repo rule that new features ship with a test,
this adds one.

**New dev dependencies, flagged rather than assumed:** `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `jsdom`. Script: `npm test`.

What gets tested is the extracted hooks, where the real logic lives:

- `useRecorder` — the speech-peak gate rejects a silent clip; the minimum-duration guard
  rejects a too-short one; a valid clip reaches transcription.
- `useDsaRound` — the snapshot debounce does not fire for untouched starter code (the
  guard that protects the watcher's typing clock); a `silent` check-in appends nothing.
- `useSession` — a failed answer rolls back the optimistic history append.
- `Transcript` — renders both variants without losing turns.

Backend: one test that `DsaPayload` carries `prompt` through the session endpoints.

Existing `pytest` suite must stay green; no test is edited to accommodate a change.

---

## 6. Delivery — three PRs

**PR 1 — Rename, tokens, shell.** Callback everywhere user-visible, the monochrome token
set, `#root` cleanup, header lockup, favicon and OG card, landing hero and line art.
ADR 0030. Visible, self-contained, no behaviour change.

**PR 2 — Component and hook extraction.** The `App.jsx` split, plus the Vitest setup and
hook tests. Pure refactor; no visual change beyond what PR 1 established.

**PR 3 — Coding round.** `DsaPayload.prompt` and its backend test, `CodingWorkspace`,
`InterviewerRail`, the wide layout mode, the run-results table.

Each is a feature branch off `main` with its own PR.

---

## 7. Assets

Supplied externally (generated with ChatGPT), to this specification:

1. **Hero illustration** — monoline scene: a desk, laptop, chair, lamp, a window, and
   concentric arcs suggesting voice. White stroke on transparent, ~1.1px at 40px scale,
   round caps and joins, no fill, no shading. Wide crop, intended to bleed off the right
   edge behind the headline at ~50% opacity.
2. **Four section icons** — résumé, voice, coding round, evaluation. Same stroke weight and
   style, 40×40 artboard, so one set covers the landing steps and section markers.
3. **Wordmark** — "Callback", SVG, single colour so it inherits `currentColor`. The idea to
   draw is the *return*: an arrow curving back, a bracket closing, a call returning. Not a
   chat bubble.
4. **Favicon** — the mark alone, 32×32 and 180×180 PNG.
5. **OG image** — 1200×630, black `#0c0c0c`, white line art and type, name plus descriptor.

The landing carries the hero illustration and the four icons, and nothing else — no
secondary scenes. The existing `frontend/src/assets/hero.png` is referenced nowhere and is
deleted in PR 1.

---

## 8. Assumptions

- Dark-only is acceptable for this pass; no light theme ships.
- The system serif stack is acceptable in place of a self-hosted display face.
- The coding question appears both pinned above the editor and in the transcript.
- `mockmate` survives as an internal identifier indefinitely, not as a migration debt.
- Line art is supplied before PR 1 merges; if it is late, PR 1 ships with the type-only
  hero and the art lands as a follow-up.
