# Callback PR 1 — Rename and Visual System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename MockMate to Callback everywhere a user can see it, and replace the
half-finished styling with a monochrome design system that every screen actually uses.

**Architecture:** Two CSS files carry the whole system — `index.css` holds tokens and
element defaults, `App.css` holds component rules that reference only those tokens. No
hardcoded colour survives. `App.jsx` changes only where strings, class names, or the new
hero markup require it; no logic, no hooks, no state changes. The component split and the
coding-round rebuild are PR 2 and PR 3 and are explicitly out of scope here.

**Tech Stack:** React 19, Vite 8, plain CSS with custom properties, oxlint, FastAPI +
pytest on the backend.

## Global Constraints

- Product name in all user-visible text: **Callback**. Lockup: `Callback — voice interview practice, in the open`.
- The identifier `mockmate` **stays** in `infra/*.tf`, the GitHub repo slug, the CI badge URL, the Docker image name, the Render service name, and the env vars `MOCKMATE_DDB_TABLE` / `MOCKMATE_EVAL_WAIT_SECONDS`. Renaming those is a destroy-and-recreate against live AWS resources and is not in this PR.
- Palette, exact values: `--bg: #0c0c0c`, `--surface: #151515`, `--surface-2: #1c1c1c`, `--border: #262626`, `--border-strong: #3a3a3a`, `--text: #fafafa`, `--text-muted: #8a8a8a`, `--text-dim: #5c5c5c`, `--pass: #3fb950`, `--fail: #e5484d`, `--pending: #d29922`.
- Colour is reserved for state. `--pass`, `--fail` and `--pending` may only be used for test results and transient status. No other element in the app is coloured.
- Spacing scale: `4 8 12 16 24 32 48 64` px only. Radii: `2px` default, `4px` for code surfaces. No pills, no glass, no gradients, no glow, no shadow.
- Dark only. `color-scheme: dark`. No `prefers-color-scheme` block.
- Display type is the system serif stack `'Iowan Old Style', Georgia, 'Times New Roman', serif`. No web font is downloaded.
- Every commit message is imperative mood and carries no Claude/Anthropic attribution of any kind.
- Work happens on branch `feat/callback-rename-visual-system`, cut from `origin/main`.

## Deviation from the spec, stated up front

The spec assigns "landing hero and line art" to PR 1 and leaves the interview screen's
restyle unassigned. That does not survive contact with the code: replacing the tokens in
`index.css` while `App.css` still hardcodes `#555`/`#888`/`#7ab` leaves the interview and
evaluation screens visibly broken between PR 1 and PR 2. **So PR 1 restyles every screen**
— transcript speaker rules, composer, chips, evaluation, and the existing DSA pane in its
current single-column shape. PR 3 still owns the coding round's *layout* rebuild. PR 2
remains a pure extraction with no visual change.

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `docs/decisions/0030-callback-rename-and-visual-system.md` | Records the rename split and the monochrome decision | Create |
| `frontend/src/index.css` | Tokens, element defaults, `#root` | Rewrite |
| `frontend/src/App.css` | All component rules, token-only | Rewrite |
| `frontend/src/App.jsx` | Strings, lockup header, hero markup, new class names | Modify |
| `frontend/index.html` | Title, description, OG/Twitter tags, favicon links | Modify |
| `frontend/src/assets/hero-art.png` | Landing line art, cropped from the supplied hero | Create (derived) |
| `frontend/public/og.png` | Social preview card, resized from the supplied hero | Create (derived) |
| `frontend/public/favicon.svg` | Callback return mark | Replace |
| `frontend/src/assets/mark.svg` | Return mark beside the header wordmark | Create |
| `frontend/public/icons.svg` | Bluesky/Discord template cruft | Delete |
| `frontend/src/assets/hero.png`, `react.svg`, `vite.svg` | Unreferenced template leftovers | Delete |
| `frontend/src/assets/Hero_gpt.png`, `Wordmark.png`, `Icons.png` | Supplied originals; kept as sources | Keep, uncompiled |
| `backend/app/main.py` | FastAPI title and module docstring | Modify |
| `backend/tests/test_main.py` | Asserts the API advertises Callback | Modify |
| `README.md`, `docs/decisions/README.md` | Product name in prose | Modify |

---

### Task 1: Record the decision (ADR 0030)

**Files:**
- Create: `docs/decisions/0030-callback-rename-and-visual-system.md`
- Modify: `docs/decisions/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the ADR number `0030`, cited by later commit messages and by code comments in Task 3 and Task 5.

- [ ] **Step 1: Confirm 0030 is free and check the ADR house style**

```bash
ls docs/decisions/ | tail -3
head -30 docs/decisions/0029-serverless-aws-deploy.md
```

Expected: highest existing number is `0029`; the file opens with a title, a `**Status:**`
line, then `## Context`, `## Decision`, `## Consequences`. Match whatever you see — the
skeleton below assumes that shape and must be adjusted if it differs.

- [ ] **Step 2: Create the branch**

```bash
git checkout -b feat/callback-rename-visual-system origin/main
```

- [ ] **Step 3: Write the ADR**

Create `docs/decisions/0030-callback-rename-and-visual-system.md`:

```markdown
# 0030 — Callback: rename, and a monochrome visual system

**Status:** Accepted

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
failing ones, plus `#d29922` for transient status. This is functional before it is
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
```

- [ ] **Step 4: Add it to the ADR index**

Open `docs/decisions/README.md`, find the row for `0029`, and add a row beneath it in the
same format the file already uses. Also change the line
`The single roll-up of every architectural decision in MockMate — what's decided,`
to read `... in Callback — what's decided,`.

- [ ] **Step 5: Verify the index renders and nothing else changed**

```bash
git diff --stat
```

Expected: exactly two files — `docs/decisions/0030-...md` (new) and
`docs/decisions/README.md` (small edit).

- [ ] **Step 6: Commit**

```bash
git add docs/decisions/
git commit -m "Add ADR 0030: rename to Callback and a monochrome visual system"
```

---

### Task 2: Replace the design tokens

**Files:**
- Modify: `frontend/src/index.css` (full rewrite, currently 111 lines)

**Interfaces:**
- Consumes: nothing.
- Produces: the custom properties `--bg --surface --surface-2 --border --border-strong --text --text-muted --text-dim --pass --fail --pending --serif --sans --mono --r --r-code` and the spacing scale `--s1`…`--s8`. Every later task references these names exactly.

- [ ] **Step 1: Replace `index.css` entirely**

```css
/* Design tokens (ADR 0030). Monochrome: colour is reserved for state, which
   means --pass, --fail and --pending may only describe test results and
   transient status. Nothing else in the app is coloured. */
:root {
  --bg: #0c0c0c;
  --surface: #151515;
  --surface-2: #1c1c1c;
  --border: #262626;
  --border-strong: #3a3a3a;

  --text: #fafafa;
  --text-muted: #8a8a8a;
  --text-dim: #5c5c5c;

  --pass: #3fb950;
  --fail: #e5484d;
  --pending: #d29922;

  --serif: 'Iowan Old Style', Georgia, 'Times New Roman', serif;
  --sans: system-ui, 'Segoe UI', Roboto, sans-serif;
  --mono: ui-monospace, Consolas, monospace;

  /* Spacing scale. These are the only gaps, paddings and margins used. */
  --s1: 4px;
  --s2: 8px;
  --s3: 12px;
  --s4: 16px;
  --s5: 24px;
  --s6: 32px;
  --s7: 48px;
  --s8: 64px;

  --r: 2px;
  --r-code: 4px;

  font: 16px/1.6 var(--sans);
  color-scheme: dark;
  color: var(--text);
  background: var(--bg);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  margin: 0;
  background: var(--bg);
}

#root {
  min-height: 100svh;
  display: flex;
  flex-direction: column;
}

h1,
h2,
h3 {
  font-family: var(--serif);
  font-weight: 400;
  color: var(--text);
  letter-spacing: -0.02em;
  margin: 0;
}

h1 { font-size: 2rem; line-height: 1.1; }
h2 { font-size: 1.5rem; line-height: 1.15; }
h3 { font-size: 1.125rem; line-height: 1.2; }

p { margin: 0; }

a {
  color: var(--text);
  text-decoration: none;
  border-bottom: 1px solid var(--border-strong);
}

a:hover { border-bottom-color: var(--text); }

code {
  font-family: var(--mono);
  font-size: 0.875em;
  padding: 2px 6px;
  border-radius: var(--r-code);
  background: var(--surface-2);
  color: var(--text);
}

button {
  font: inherit;
  font-size: 0.875rem;
  padding: var(--s2) var(--s4);
  border-radius: var(--r);
  border: 1px solid var(--text);
  background: var(--text);
  color: var(--bg);
  cursor: pointer;
}

button:hover:not(:disabled) { background: #fff; }

button:disabled {
  background: transparent;
  border-color: var(--border);
  color: var(--text-dim);
  cursor: default;
}

input,
select,
textarea {
  font: inherit;
  font-size: 0.875rem;
  padding: var(--s2) var(--s3);
  border-radius: var(--r);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
}

input:focus,
select:focus,
textarea:focus {
  outline: none;
  border-color: var(--border-strong);
}

::placeholder { color: var(--text-dim); }
```

- [ ] **Step 2: Confirm the app still builds**

```bash
cd frontend && npm run build
```

Expected: `built in …ms`, no errors. The app will look wrong at this point — `App.css`
still overrides with its own hardcoded colours. That is expected and Task 3 fixes it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "Replace the design tokens with the monochrome set (ADR 0030)"
```

---

### Task 3: Rewrite the component styles against the tokens

**Files:**
- Modify: `frontend/src/App.css` (full rewrite, currently 247 lines)

**Interfaces:**
- Consumes: every token defined in Task 2.
- Produces: the class names `.wrap .wrap--wide .topbar .brand .brand-name .brand-tag .controls .voice-row .status .progress .landing .hero .hero-art .hero-body .kicker .landing-steps .start-panel .resume-drop .fallback-offer .chat .messages .turn .turn-label .turn-text .composer .banner .hint .dsa-pane .dsa-signature .dsa-actions .dsa-results .dsa-fail .evaluation .evaluation-question .score-row .score-bar`, all consumed by Task 5.

- [ ] **Step 1: Replace `App.css` entirely**

```css
/* Component styles (ADR 0030). Every value here comes from a token in
   index.css - no literal colour, no gap outside the spacing scale. */

.wrap {
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: var(--s5) var(--s4);
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  box-sizing: border-box;
}

/* PR 3 widens the page for the coding round by adding this class. Defined now
   so the layout mode exists before the round is rebuilt. */
.wrap--wide { max-width: 1140px; }

/* ---- header ---------------------------------------------------------- */

.topbar {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s3);
  padding-bottom: var(--s4);
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--s5);
}

.brand {
  display: flex;
  align-items: baseline;
  gap: var(--s3);
}

.brand-name {
  font-family: var(--serif);
  font-size: 1.25rem;
  color: var(--text);
}

/* The return mark, sized to the wordmark's cap height. */
.brand-mark {
  height: 0.75em;
  width: auto;
  opacity: 0.85;
}

.brand-tag {
  font-size: 0.75rem;
  color: var(--text-dim);
}

.controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s4);
}

.voice-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-size: 0.75rem;
  color: var(--text-muted);
}

/* One indicator instead of three spans. The dot carries state colour; the
   word stays neutral so the colour reads as signal, not decoration. */
.status {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  font-size: 0.75rem;
  color: var(--text-muted);
}

.status::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-dim);
}

.status-recording::before { background: var(--fail); }
.status-transcribing::before,
.status-thinking::before { background: var(--pending); }
.status-speaking::before { background: var(--text); }

.progress {
  font-family: var(--mono);
  font-size: 0.6875rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-dim);
}

/* ---- landing --------------------------------------------------------- */

.hero {
  position: relative;
  overflow: hidden;
  margin-bottom: var(--s6);
}

.hero-art {
  position: absolute;
  right: -32px;
  top: 50%;
  transform: translateY(-50%);
  height: 300px;
  opacity: 0.35;
  pointer-events: none;
}

.hero-body {
  position: relative;
  max-width: 460px;
}

.kicker {
  font-family: var(--mono);
  font-size: 0.6875rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: var(--s4);
}

.hero h1 {
  font-size: clamp(2rem, 6vw, 3rem);
  margin-bottom: var(--s4);
}

.landing .lede {
  color: var(--text-muted);
  margin-bottom: var(--s5);
}

.landing-steps {
  list-style: none;
  padding: 0;
  margin: 0 0 var(--s5);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  color: var(--text-muted);
  font-size: 0.875rem;
}

.landing-steps li {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  padding-left: var(--s3);
  border-left: 1px solid var(--border);
}

/* ---- start panel ----------------------------------------------------- */

.start-panel {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  align-items: flex-start;
}

.resume-drop {
  width: 100%;
  padding: var(--s5);
  border: 1px dashed var(--border-strong);
  border-radius: var(--r);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  cursor: pointer;
  box-sizing: border-box;
}

.resume-drop:hover { border-color: var(--text-dim); }

.resume-drop input { display: none; }

.fallback-offer {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  align-items: flex-start;
  padding: var(--s4);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--surface);
}

button.secondary {
  background: transparent;
  border-color: var(--border-strong);
  color: var(--text-muted);
}

button.secondary:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--text);
}

button.recording {
  background: transparent;
  border-color: var(--fail);
  color: var(--fail);
}

/* ---- chat ------------------------------------------------------------ */

.chat {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--surface);
  overflow: hidden;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--s5);
  display: flex;
  flex-direction: column;
  gap: var(--s5);
}

/* Speaker rules, not bubbles: a small-caps label over the text with a rule
   down the left edge. The interviewer's rule is solid; yours is quiet. */
.turn {
  border-left: 2px solid var(--border);
  padding-left: var(--s3);
}

.turn.assistant { border-left-color: var(--text); }

.turn-label {
  display: block;
  font-family: var(--mono);
  font-size: 0.625rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: var(--s1);
}

.turn.assistant .turn-label { color: var(--text-muted); }

.turn-text { color: var(--text-muted); }

.turn.assistant .turn-text { color: var(--text); }

.turn.wrap-up .turn-text { font-family: var(--serif); font-size: 1.0625rem; }

.composer {
  display: flex;
  gap: var(--s2);
  padding: var(--s3);
  border-top: 1px solid var(--border);
  background: var(--surface-2);
}

.composer input { flex: 1; }

/* ---- messages to the user -------------------------------------------- */

.banner {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  margin-bottom: var(--s4);
  border: 1px solid var(--fail);
  border-radius: var(--r);
  background: var(--surface);
  color: var(--text);
  font-size: 0.875rem;
}

.banner button {
  background: transparent;
  border: none;
  color: var(--text-muted);
  padding: 0;
}

.hint {
  font-size: 0.8125rem;
  color: var(--text-dim);
}

/* ---- coding round (current single-column shape; PR 3 rebuilds it) ----- */

.dsa-pane {
  border-top: 1px solid var(--border);
  padding: var(--s3);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.dsa-signature {
  font-family: var(--mono);
  font-size: 0.8125rem;
  color: var(--text-muted);
}

.dsa-pane .cm-editor {
  border: 1px solid var(--border);
  border-radius: var(--r-code);
  font-size: 0.8125rem;
  text-align: left;
}

.dsa-actions { display: flex; gap: var(--s2); }

.dsa-results { font-size: 0.8125rem; }

/* Unscoped on purpose: the evaluation's coding section reuses these outside
   .dsa-results. These two are the only coloured text in the app. */
.passed { color: var(--pass); }
.failed { color: var(--fail); }

.dsa-fail {
  color: var(--text-muted);
  margin-top: var(--s1);
}

/* ---- evaluation ------------------------------------------------------ */

.evaluation {
  margin-top: var(--s5);
  padding: var(--s5);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--surface);
}

.evaluation h3 {
  margin: var(--s5) 0 var(--s3);
  color: var(--text-muted);
  font-family: var(--sans);
  font-size: 0.6875rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.evaluation ul {
  margin: 0;
  padding-left: var(--s4);
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.evaluation-assessment { color: var(--text); }

/* Scores read badly as text on a 1-5 scale, so they get a bar. */
.score-row {
  display: grid;
  grid-template-columns: 140px 1fr 32px;
  align-items: center;
  gap: var(--s3);
  font-size: 0.8125rem;
  color: var(--text-muted);
  margin-bottom: var(--s2);
}

.score-bar {
  height: 4px;
  border-radius: var(--r);
  background: var(--surface-2);
  overflow: hidden;
}

.score-bar > span {
  display: block;
  height: 100%;
  background: var(--text);
}

.evaluation-question {
  border-top: 1px solid var(--border);
  padding-top: var(--s4);
  margin-top: var(--s4);
}

.evaluation-question-text {
  color: var(--text);
  margin-bottom: var(--s3);
}

@media (max-width: 640px) {
  .wrap { padding: var(--s4) var(--s3); }
  .hero-art { display: none; }
  .messages { padding: var(--s4); gap: var(--s4); }
}
```

- [ ] **Step 2: Build and lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: build succeeds, oxlint reports no errors.

- [ ] **Step 3: Confirm no hardcoded colour survives**

```bash
grep -nE '#[0-9a-fA-F]{3,8}' frontend/src/App.css
```

Expected: **no output**. Any hit is a token that was missed — fix it before committing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.css
git commit -m "Rewrite the component styles against the design tokens (ADR 0030)"
```

---

### Task 4: Rename the product in code and docs

**Files:**
- Modify: `backend/app/main.py:1`, `backend/app/main.py:82`
- Modify: `backend/tests/test_main.py`
- Modify: `README.md:1`, `README.md:5-7`
- Test: `backend/tests/test_main.py::test_api_advertises_the_product_name`

**Interfaces:**
- Consumes: nothing.
- Produces: `FastAPI(title="Callback")`, which the test asserts and the `/docs` page displays.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_main.py`, following the import and client conventions already
in that file:

```python
def test_api_advertises_the_product_name():
    """The rename is display-only (ADR 0030), and this is the one place the API
    shows a name to a human - the generated /docs page."""
    from app.main import app

    assert app.title == "Callback"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd backend && pytest tests/test_main.py::test_api_advertises_the_product_name -v
```

Expected: FAIL — `AssertionError: assert 'MockMate' == 'Callback'`.

- [ ] **Step 3: Rename in `backend/app/main.py`**

Line 82, change:

```python
app = FastAPI(title="MockMate")
```

to:

```python
app = FastAPI(title="Callback")
```

Line 1, change the docstring opening from `"""MockMate interviewer agent API` to
`"""Callback interviewer agent API`.

- [ ] **Step 4: Run the test and the whole suite**

```bash
cd backend && pytest tests/test_main.py::test_api_advertises_the_product_name -v && pytest -q
```

Expected: the new test passes, and the full suite is green with no new failures.

- [ ] **Step 5: Leave the infrastructure identifiers alone — verify you did**

```bash
grep -rn "MOCKMATE_\|mockmate" backend/app/ --include=*.py
```

Expected: exactly two hits, both untouched —
`main.py` `os.getenv("MOCKMATE_EVAL_WAIT_SECONDS", "30.0")` and
`session_store.py` `os.getenv("MOCKMATE_DDB_TABLE", "mockmate")`. These are read by
Terraform-provisioned environment variables. Renaming them breaks the deploy.

The `MockMate` strings inside `test_main.py` and `test_resume.py` fixtures are sample
résumé prose, not product name. Leave them.

- [ ] **Step 6: Rename in the README**

Line 1: `# MockMate (working title)` becomes:

```markdown
# Callback

> Voice interview practice, in the open.
```

Then in the paragraph beginning "A voice-based AI mock interviewer you can run for free",
replace `AI mock interviewer` with `AI interviewer`. Leave lines 102, 107, 127 and 128
alone — `mockmate-api` is the Render service and Docker image name.

- [ ] **Step 7: Confirm the badge URL is untouched**

```bash
grep -n "badge.svg" README.md
```

Expected: still points at `github.com/SaixAbhinav/mockmate` — the repo slug does not change.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py README.md
git commit -m "Rename the product to Callback in user-visible text (ADR 0030)"
```

---

### Task 5: Rebuild the app chrome and landing markup

**Files:**
- Modify: `frontend/src/App.jsx:451-526` (start screen), `:536-563` (header), `:564-578` (messages), `:609-625` (run results), `:661-761` (evaluation), `:763` (error)
- Delete: `frontend/src/assets/hero.png`

**Interfaces:**
- Consumes: every class name produced by Task 3; `hero-art.png` and `mark.svg` from Task 6.
- Produces: no new exports. `App.jsx` still default-exports `App`.

> **Order note:** Task 6 creates the two image files this task imports. Either run Task 6
> first, or expect `npm run build` to fail on a missing import until it is done.

- [ ] **Step 1: Add the asset imports**

At the top of `App.jsx`, beneath the existing `import './App.css'`:

```jsx
import heroArt from './assets/hero-art.png'
import mark from './assets/mark.svg'
```

- [ ] **Step 2: Replace the start screen's return block**

In `App.jsx`, replace the whole `if (screen === 'start') { return (…) }` body with:

```jsx
  if (screen === 'start') {
    return (
      <main className="wrap">
        <header className="topbar">
          <div className="brand">
            <span className="brand-name">Callback</span>
            <img className="brand-mark" src={mark} alt="" aria-hidden="true" />
            <span className="brand-tag">voice interview practice, in the open</span>
          </div>
        </header>

        <div className="landing">
          <section className="hero">
            <img className="hero-art" src={heroArt} alt="" aria-hidden="true" />
            <div className="hero-body">
              <p className="kicker">Open source · self-hostable</p>
              <h1>Sit the interview before it counts.</h1>
              <p className="lede">
                Upload a résumé and Callback builds an interview around it — an intro, a
                résumé-grounded warm-up, then two sandboxed Python questions with an
                interviewer watching as you type. You leave with a scored evaluation.
              </p>
            </div>
          </section>

          <ol className="landing-steps">
            <li>Upload a résumé — optional, skip it for a general ML/GenAI interview</li>
            <li>Answer out loud; the interviewer probes what you say</li>
            <li>Solve two coding questions, then read your scored evaluation</li>
          </ol>

          <p className="hint">
            Built in the open —{' '}
            <a href="https://github.com/SaixAbhinav/mockmate" target="_blank" rel="noreferrer">
              source and architecture decisions on GitHub
            </a>
            .
          </p>
        </div>

        <section className="start-panel">
          <label className="resume-drop">
            <strong>{resumeName || 'Choose a résumé'}</strong>
            <span className="hint">
              {resumeStatus === 'uploading'
                ? 'Uploading…'
                : resumeStatus === 'ready'
                  ? 'Your interview will be built around this file'
                  : 'PDF or .txt — or skip for a general ML/GenAI interview'}
            </span>
            <input type="file" accept=".pdf,.txt" onChange={handleResumeChange} />
          </label>

          {fallbackOffer ? (
            <div className="fallback-offer">
              <p>{fallbackOffer.message}</p>
              <div className="dsa-actions">
                <button onClick={() => startInterview(true)} disabled={status === 'thinking'}>
                  Start the general interview
                </button>
                <button
                  className="secondary"
                  onClick={() => setFallbackOffer(null)}
                  disabled={status === 'thinking'}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => startInterview(false)}
              disabled={status === 'thinking' || resumeStatus === 'uploading'}
            >
              {status === 'thinking'
                ? (resumeId ? 'Reading your résumé…' : 'Starting…')
                : !apiReady
                  ? 'Start interview — waking the interviewer'
                  : 'Start interview'}
            </button>
          )}
          {!apiReady && (
            <p className="hint">The first visit can take up to a minute to wake (ADR 0025).</p>
          )}
        </section>

        {error && (
          <div className="banner">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
              ✕
            </button>
          </div>
        )}
      </main>
    )
  }
```

- [ ] **Step 3: Replace the interview header**

Replace the `<header className="topbar">…</header>` block in the second return with:

```jsx
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">Callback</span>
          <img className="brand-mark" src={mark} alt="" aria-hidden="true" />
          {progressLabel && <span className="progress">{progressLabel}</span>}
        </div>
        <div className="controls">
          <label className="voice-row">
            Voice:
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {Object.entries(voices).map(([id, label]) => (
                <option key={id} value={id}>{label}</option>
              ))}
            </select>
          </label>
          <span
            className={`status status-${status}`}
            title={latencyMs !== null ? `last turn: ${latencyMs} ms` : undefined}
          >
            {status}
          </span>
        </div>
      </header>
```

- [ ] **Step 4: Replace the message list with speaker-ruled turns**

Replace the `history.map(…)` block with:

```jsx
          {history.map((m, i) => (
            <div
              key={i}
              className={`turn ${m.role}${done && i === history.length - 1 ? ' wrap-up' : ''}`}
            >
              <span className="turn-label">{m.role === 'user' ? 'You' : 'Interviewer'}</span>
              <p className="turn-text">{m.content}</p>
            </div>
          ))}
```

- [ ] **Step 5: Replace the run-results block**

Replace the `{runReport && (…)}` block inside `.dsa-pane` with:

```jsx
                {runReport && (
                  <div className="dsa-results">
                    {runReport.status === 'ok' ? (
                      <p className={runReport.passed === runReport.total ? 'passed' : 'failed'}>
                        {runReport.passed} of {runReport.total} test cases passed
                      </p>
                    ) : (
                      <p className="failed">{runReport.error}</p>
                    )}
                    {runReport.results.filter((r) => !r.passed).map((r, i) => (
                      <p key={i} className="dsa-fail">
                        <code>{JSON.stringify(r.args)}</code> → expected{' '}
                        <code>{JSON.stringify(r.expected)}</code>, got <code>{r.got}</code>
                      </p>
                    ))}
                  </div>
                )}
```

- [ ] **Step 6: Replace the score chips with bars**

Add this helper just above `function App() {`:

```jsx
// Scores are 1-5; a bar reads faster than a number in a pill.
function ScoreRow({ label, value }) {
  return (
    <div className="score-row">
      <span>{label}</span>
      <span className="score-bar">
        <span style={{ width: `${((value ?? 0) / 5) * 100}%` }} />
      </span>
      <span>{value ?? '—'}</span>
    </div>
  )
}
```

Then replace each `<div className="chips">…</div>` block in the evaluation section with
`ScoreRow` calls. The overall averages block becomes:

```jsx
          <p className="hint">
            answered {evaluation.coverage.answered} of {evaluation.coverage.total}
          </p>
          {Object.entries(evaluation.averages).map(([dimension, value]) => (
            <ScoreRow key={dimension} label={dimension} value={value} />
          ))}
```

The per-question block becomes:

```jsx
                  <ScoreRow label="correctness" value={q.correctness} />
                  <ScoreRow label="depth" value={q.depth} />
                  <ScoreRow label="clarity" value={q.clarity} />
```

The coding-round averages block becomes:

```jsx
              {Object.entries(evaluation.dsa.averages).map(([dimension, value]) => (
                <ScoreRow key={dimension} label={dimension.replace('_', ' ')} value={value} />
              ))}
              <p className="hint">hints used: {evaluation.dsa.hints_used}</p>
```

And the per-coding-question block becomes:

```jsx
                    <>
                      <p className={q.tests.passed === q.tests.total ? 'passed' : 'failed'}>
                        tests: {q.tests.passed}/{q.tests.total}
                        {q.tests.status !== 'ok' && ` (${q.tests.status})`}
                      </p>
                      {!q.unscored && (
                        <>
                          <ScoreRow label="code quality" value={q.code_quality} />
                          <ScoreRow label="approach" value={q.approach} />
                        </>
                      )}
                    </>
```

- [ ] **Step 7: Replace the trailing error paragraph with the banner**

Replace the final `{error && <p className="error">{error}</p>}` with:

```jsx
      {error && (
        <div className="banner">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}
```

Move it so it renders **directly after the `</header>`**, not at the bottom of the
component — during the coding round the bottom of the page is below the fold.

- [ ] **Step 8: Delete the unreferenced template image**

```bash
git rm frontend/src/assets/hero.png frontend/src/assets/react.svg frontend/src/assets/vite.svg
grep -rn "assets/hero.png\|react.svg\|vite.svg" frontend/src frontend/index.html
```

Expected: the grep returns nothing. `Hero_gpt.png`, `Wordmark.png` and `Icons.png` stay —
they are the supplied sources the derived assets come from.

- [ ] **Step 9: Build and lint**

```bash
cd frontend && npm run build && npm run lint
```

Expected: both clean. If oxlint flags `ScoreRow` for a missing prop-types rule, follow
whatever the existing `.oxlintrc.json` config expects rather than adding a new dependency.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "Rebuild the app chrome and landing on the new visual system (ADR 0030)"
```

---

### Task 6: Assets, page metadata, and template cleanup

**Files:**
- Create: `frontend/src/assets/hero-art.png`, `frontend/src/assets/mark.svg`, `frontend/public/og.png`
- Replace: `frontend/public/favicon.svg`
- Delete: `frontend/public/icons.svg`
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: the supplied `frontend/src/assets/Hero_gpt.png` (1713×907, line art with the wordmark and tagline set into the left half).
- Produces: `hero-art.png` and `mark.svg`, imported by Task 5; `/og.png` and `/favicon.svg`, referenced by `index.html`; the document title `Callback — voice interview practice, in the open`.

> **On the artwork:** the supplied hero is a finished lockup — wordmark, tagline and scene
> in one image at almost exactly the 1.91:1 Open Graph ratio. It is therefore used *whole*
> as the social card, and *cropped to the scene* for the landing, where the headline is
> live HTML and a second baked-in wordmark would collide with it. Both derivations are
> deterministic commands below; no hand-editing in an image editor.

- [ ] **Step 1: Derive the Open Graph card**

```bash
cd frontend && python -c "
from PIL import Image
im = Image.open('src/assets/Hero_gpt.png').convert('RGB')
im.resize((1200, 630), Image.LANCZOS).save('public/og.png', optimize=True)
print(Image.open('public/og.png').size)
"
```

Expected: `(1200, 630)`. Confirm the file is under 300 KB:

```bash
ls -l frontend/public/og.png
```

- [ ] **Step 2: Derive the landing art by cropping off the baked-in wordmark**

The scene occupies roughly the right 55% of the source. Crop it, then downscale to a
sensible display width so a 1 MB PNG is not shipped to every visitor:

```bash
cd frontend && python -c "
from PIL import Image
im = Image.open('src/assets/Hero_gpt.png').convert('RGBA')
w, h = im.size
art = im.crop((int(w * 0.45), 0, w, h))
art.thumbnail((900, 900), Image.LANCZOS)
art.save('src/assets/hero-art.png', optimize=True)
print(art.size)
"
ls -l frontend/src/assets/hero-art.png
```

Expected: roughly `(900, 480)` and well under 300 KB. Open the file and confirm no part of
the word "Callback" or the tagline is still visible — if any letter survives, raise the
`0.45` and run it again.

- [ ] **Step 3: Create the return mark**

The wordmark's arrow, redrawn as vector so it stays crisp at header size and inherits
colour. Create `frontend/src/assets/mark.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="#fafafa" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
  <path d="M20 13a8 8 0 1 1-4.5-7.2"/>
  <path d="M20 4v5h-5"/>
</svg>
```

If the externally generated vector mark arrives later, it replaces this file with no code
change.

- [ ] **Step 4: Replace `frontend/public/favicon.svg`**

The current file is a purple gradient bolt from a starter template. Replace its entire
contents with a mark on the same monoline system — a call returning:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none"
     stroke="#fafafa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect width="32" height="32" rx="4" fill="#0c0c0c" stroke="none"/>
  <path d="M22 10H13a5 5 0 000 10h9"/>
  <path d="M17 15l-5 5 5 5" transform="translate(0 -5)"/>
</svg>
```

- [ ] **Step 5: Delete the template icon sheet**

```bash
git rm frontend/public/icons.svg
grep -rn "icons.svg" frontend/src frontend/index.html
```

Expected: the grep returns nothing — it was referenced nowhere.

- [ ] **Step 6: Rewrite `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Callback — voice interview practice, in the open</title>
    <meta name="description" content="Upload a résumé and sit a voice interview: a résumé-grounded warm-up, two sandboxed Python questions with an interviewer watching, and a scored evaluation. Open source and self-hostable." />
    <meta name="theme-color" content="#0c0c0c" />

    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />

    <meta property="og:type" content="website" />
    <meta property="og:title" content="Callback — voice interview practice, in the open" />
    <meta property="og:description" content="Sit the interview before it counts. Résumé-grounded questions, a sandboxed coding round, and a scored evaluation." />
    <meta property="og:image" content="/og.png" />
    <meta name="twitter:card" content="summary_large_image" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 7: Generate the touch icon from the favicon mark**

```bash
cd frontend && python -c "
from PIL import Image, ImageDraw
im = Image.new('RGB', (180, 180), '#0c0c0c')
d = ImageDraw.Draw(im)
d.arc([40, 40, 140, 140], start=310, end=250, fill='#fafafa', width=9)
d.line([(140, 40), (140, 68)], fill='#fafafa', width=9)
d.line([(140, 40), (112, 40)], fill='#fafafa', width=9)
im.save('public/apple-touch-icon.png', optimize=True)
print('ok')
"
```

This is a deliberate approximation of the SVG mark for the one context that cannot take
vector. If the generated vector mark arrives, re-render this from it.

- [ ] **Step 8: Note what is still owed**

The four section icons are **not** in this PR. The supplied `Icons.png` is dark strokes on
a grey gradient background, which is invisible on `#0c0c0c`, and it is a single sheet that
would need slicing. It is being regenerated as white-on-transparent. The landing steps
render as text with left rules until then — that is a complete design, not a placeholder,
so nothing is blocked.

- [ ] **Step 9: Build and confirm the assets are emitted and hashed**

```bash
cd frontend && npm run build && ls dist/ && ls dist/assets/ | head
```

Expected: `dist/favicon.svg`, `dist/og.png` and `dist/apple-touch-icon.png` are present at
the root; `hero-art-<hash>.png` and `mark-<hash>.svg` are under `dist/assets/`;
`dist/icons.svg` is gone.

- [ ] **Step 10: Check the shipped weight**

```bash
du -sh frontend/dist && ls -lS frontend/dist/assets | head -5
```

Expected: no single asset over ~300 KB. The supplied 1–2 MB sources stay in `src/assets/`
as originals and are never served — only the derived files are.

- [ ] **Step 11: Commit**

```bash
git add frontend/public frontend/src/assets frontend/index.html
git commit -m "Add the Callback mark, derived hero art and page metadata (ADR 0030)"
```

---

### Task 7: Verify the whole PR in a browser and open it

**Files:** none modified.

**Interfaces:**
- Consumes: everything above.
- Produces: a pushed branch and an open PR.

- [ ] **Step 1: Run everything that can fail**

```bash
cd backend && pytest -q
cd ../frontend && npm run lint && npm run build
```

Expected: pytest green, oxlint silent, build succeeds. If anything fails, fix it — do not
proceed and do not edit a test to make it pass.

- [ ] **Step 2: Start the dev server and look at it**

Start the backend (`uvicorn app.main:app --port 8000` from `backend/`) and the frontend
preview, then check each of these in the browser:

- Start screen: serif headline, line art bleeding off the right, résumé card, black background.
- Upload a `.txt` résumé: the card shows the filename and "built around this file".
- Start an interview: header shows `Callback` plus the progress label; the status dot is amber while thinking.
- Transcript: interviewer turns have a bright left rule and light text; your turns are dimmer.
- Trigger an error — deny the microphone — and confirm the banner appears under the header, not at the page bottom, and dismisses.
- Resize to 375px: the hero art is hidden, nothing overflows horizontally.

- [ ] **Step 3: Confirm no stray product name is left where a user can see it**

```bash
grep -rn -i "mockmate" frontend/src frontend/index.html README.md | grep -v "github.com/SaixAbhinav"
```

Expected: **no output**. Hits under `infra/`, `backend/app/session_store.py`, the
`MOCKMATE_*` env vars, and the CI badge URL are intentional and are not searched here.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/callback-rename-visual-system
gh pr create --base main --title "Rename to Callback and ship the monochrome visual system (ADR 0030, PR 1)" --body "..."
```

The body covers: what changed, the display-only rename decision and why `mockmate` stays in
`infra/`, the deviation from the spec recorded above, the section icons still owed (the
supplied sheet is dark-on-grey and is being regenerated white-on-transparent), and the
verification actually run. No Claude or
Anthropic attribution anywhere.

- [ ] **Step 5: Report it briefly**

Per repo convention: the PR link, one line on what it does, test status, and anything
needing a decision. The detail lives in the PR description.

---

## Out of scope, tracked for later PRs

- **PR 2** — hook and component extraction, Vitest setup, hook tests.
- **PR 3** — `DsaPayload.prompt`, `CodingWorkspace`, `InterviewerRail`, the `.wrap--wide` layout mode, the run-results table.
- `frontend/wireframes/MockMate_wireframe_v1.png` keeps its filename; it is a historical artefact of the original design.
- `robots.txt` still disallows all crawlers (ADR 0025), so the OG card only works for direct link unfurls. That is the intended exposure and is not changed here.
