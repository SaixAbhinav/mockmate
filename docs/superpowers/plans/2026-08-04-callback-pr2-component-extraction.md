# Callback PR 2 — Component and Hook Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 816-line `App.jsx` into focused hooks and components, behind a test suite that proves behaviour did not change.

**Architecture:** `App.jsx` becomes a shell that owns two pieces of genuinely app-level state — the activity `status` and the `error` banner — and composes seven hooks and seven components. Presentational components take props and hold no state. Hooks own one concern each and receive their cross-cutting dependencies as arguments rather than reaching for them. Nothing about interview behaviour changes; this is a pure refactor with a characterization test suite built first.

**Tech Stack:** React 19, Vite 8, Vitest 4, Testing Library, jsdom, oxlint.

## Global Constraints

- **This is a refactor. No behaviour changes.** Not a fixed bug, not a tidied edge case, not a renamed user-visible string. If a defect is found, record it in the task report and leave it in place.
- New dev dependencies, pinned exactly: `vitest@4.1.10`, `@testing-library/react@16.3.2`, `@testing-library/dom@10.4.1`, `@testing-library/jest-dom@7.0.0`, `@testing-library/user-event@14.6.3`, `jsdom@30.0.1`. No others without asking.
- Every code comment in the current `App.jsx` moves with the code it explains. These comments cite ADRs (0018, 0019, 0023, 0025, 0026) and record why non-obvious guards exist — losing them is the main risk of this refactor.
- `.oxlintrc.json` enables `react/rules-of-hooks` as an error. `npm run lint` must stay clean.
- No literal hex in any CSS. No new CSS at all — PR 1's stylesheet is final for this PR.
- Commit messages imperative mood. NEVER a `Co-Authored-By` trailer, "Generated with Claude Code", a robot emoji, or any Claude/Anthropic attribution.
- Branch `feat/callback-component-extraction`, cut from `feat/callback-rename-visual-system` (PR 1's branch, open as #46 and not yet merged). PR 2 targets that branch, not `main`, and retargets automatically when #46 merges.

## The seam design, decided up front

Two pieces of state stay in `App.jsx` rather than moving into a hook:

- **`status`** (`idle | recording | transcribing | thinking | speaking`) — a single activity indicator that the recorder, the coding round and the session all write to. Any hook that owned it would have to be imported by the other two.
- **`error`** — one banner, written from every async path.

Both are passed down as `setStatus` / `onError`. This is the correct seam, not a compromise: they are app-level UI state and every hook is a writer.

`statusRef` stays beside `status` in `App.jsx` for the same reason — the check-in poll reads it to avoid talking over the Candidate (ADR 0018).

**Deviation from the spec:** the spec named four hooks and folded résumé upload, the voice
list and the health ping into `useSession`. This plan splits those into `useResumeUpload`,
`useVoices` and `useApiReady` — seven hooks total. Each of the three is genuinely
independent of the session (the health ping and voice list run before a session exists, and
the résumé survives `startNewInterview` deliberately), so folding them in would have made
`useSession` the same tangle in a smaller file.

## File Structure

| File | Responsibility | Lines moved from `App.jsx` |
| --- | --- | --- |
| `src/lib/audio.js` | `playAudio` | 185-190 |
| `src/components/ScoreRow.jsx` | One labelled score bar | 28-46 |
| `src/components/ErrorBanner.jsx` | The dismissible banner | its markup, used twice |
| `src/components/Transcript.jsx` | Speaker-ruled message list | the `history.map` block |
| `src/components/Composer.jsx` | Text input, send, mic | the `<form className="composer">` block |
| `src/components/StartScreen.jsx` | Landing, résumé card, fallback offer | 474-583 |
| `src/components/CodingWorkspace.jsx` | Signature, editor, run/submit, results | the `.dsa-pane` block |
| `src/components/Evaluation.jsx` | The scorecard | the `.evaluation` block |
| `src/hooks/useVoices.js` | Voice list and selection | 82-90 |
| `src/hooks/useApiReady.js` | Health ping (ADR 0025) | 92-111 |
| `src/hooks/useEvaluation.js` | Scoring fetch and abort | 118-142 |
| `src/hooks/useResumeUpload.js` | Upload, supersede token, states | 262-292 |
| `src/hooks/useRecorder.js` | Recorder, speech gate, transcription | 378-466 |
| `src/hooks/useDsaRound.js` | Editor state, snapshot, poll, run/submit | 144-183, 335-376 |
| `src/hooks/useSession.js` | Session lifecycle, history, progress | 192-333 |
| `src/App.jsx` | Shell: `status`, `error`, composition | — |
| `src/test/setup.js` | jsdom globals the app needs | new |
| `src/test/mocks.js` | `fetch`, `MediaRecorder`, `AudioContext`, `Audio` fakes | new |

---

### Task 1: Test harness and characterization tests

The safety net. Everything after this is judged by whether these still pass.

**Files:**
- Modify: `frontend/package.json`, `frontend/vite.config.js`
- Create: `frontend/src/test/setup.js`, `frontend/src/test/mocks.js`, `frontend/src/App.test.jsx`

**Interfaces:**
- Produces: `npm test`; `installMocks()` from `src/test/mocks.js`, which fakes `fetch`, `MediaRecorder`, `AudioContext` and `Audio` and returns a handle for asserting calls and resolving responses.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/callback-component-extraction feat/callback-rename-visual-system
```

- [ ] **Step 2: Install the pinned dev dependencies**

```bash
cd frontend && npm install -D --save-exact vitest@4.1.10 @testing-library/react@16.3.2 @testing-library/dom@10.4.1 @testing-library/jest-dom@7.0.0 @testing-library/user-event@14.6.3 jsdom@30.0.1
```

Confirm `package.json` records exact versions with no `^`.

- [ ] **Step 3: Add the test script**

In `frontend/package.json`, add to `scripts`: `"test": "vitest run"` and `"test:watch": "vitest"`.

- [ ] **Step 4: Configure Vitest**

In `frontend/vite.config.js`, add a `test` block to the existing `defineConfig` call, leaving `plugins` and `server.proxy` untouched:

```js
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
  },
```

- [ ] **Step 5: Write the setup file**

`frontend/src/test/setup.js`:

```js
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
```

- [ ] **Step 6: Write the browser-API fakes**

`frontend/src/test/mocks.js`. The app uses four browser APIs jsdom does not provide. Each fake exists because a real one is unavailable in jsdom, not to change behaviour.

```js
import { vi } from 'vitest'

// jsdom has none of these. The recorder fake is driven manually so a test can
// decide what "the Candidate spoke" or "silence" sounds like (ADR-free, but
// see the speech-peak gate in useRecorder).
export function installMocks({ peak = 0.5 } = {}) {
  const routes = new Map()
  const calls = []

  const respond = (path, body, ok = true, status = 200) =>
    routes.set(path, { body, ok, status })

  globalThis.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url)
    calls.push({ path, init })
    const match = [...routes.keys()].find((k) => path.endsWith(k))
    if (!match) throw new Error(`no mock for ${path}`)
    const { body, ok, status } = routes.get(match)
    return { ok, status, json: async () => body }
  })

  let recorderInstance = null
  class FakeMediaRecorder {
    constructor() {
      this.mimeType = 'audio/webm'
      recorderInstance = this
    }
    start() {}
    stop() {
      this.ondataavailable?.({ data: new Blob(['x']) })
      this.onstop?.()
    }
  }
  globalThis.MediaRecorder = FakeMediaRecorder

  globalThis.navigator.mediaDevices = {
    getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop() {} }] })),
  }

  // getByteTimeDomainData writes samples centred on 128; the app derives peak
  // amplitude as |sample - 128| / 128, so this yields exactly `peak`.
  class FakeAudioContext {
    createAnalyser() {
      return {
        fftSize: 2048,
        getByteTimeDomainData(arr) {
          arr.fill(128 + Math.round(peak * 128))
        },
      }
    }
    createMediaStreamSource() {
      return { connect() {} }
    }
    async close() {}
  }
  globalThis.AudioContext = FakeAudioContext

  globalThis.Audio = class {
    play() {
      this.onended?.()
      return Promise.resolve()
    }
  }

  globalThis.HTMLElement.prototype.scrollIntoView = vi.fn()

  return { respond, calls, recorder: () => recorderInstance }
}
```

- [ ] **Step 7: Write the characterization tests**

`frontend/src/App.test.jsx`. These describe what the app does TODAY. They must pass unchanged after every later task.

```jsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { installMocks } from './test/mocks'
import App from './App'

function baseRoutes(mocks) {
  mocks.respond('/api/voices', { voices: { v1: 'Voice One' }, default: 'v1' })
  mocks.respond('/api/health', { status: 'ok' })
}

describe('App', () => {
  let mocks
  beforeEach(() => {
    mocks = installMocks()
    baseRoutes(mocks)
  })

  it('shows the landing screen with the product name', async () => {
    render(<App />)
    expect(await screen.findByText('Sit the interview before it counts.')).toBeInTheDocument()
    expect(screen.getAllByText('Callback').length).toBeGreaterThan(0)
  })

  it('starts a session and shows the first question as an interviewer turn', async () => {
    mocks.respond('/api/session', {
      session_id: 's1',
      first_question: 'Tell me about yourself.',
      question_number: 1,
      total_questions: 5,
      stage: 'intro',
      warm_up_source: 'bank',
      domain: 'ml_genai',
      audio_b64: '',
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
    expect(await screen.findByText('Tell me about yourself.')).toBeInTheDocument()
    // The label is uppercased by CSS (text-transform), not in the DOM, and the
    // test environment runs with css: false.
    expect(screen.getByText('Interviewer')).toBeInTheDocument()
  })

  it('rolls the transcript back when an answer fails, leaving no orphan turn', async () => {
    mocks.respond('/api/session', {
      session_id: 's1',
      first_question: 'Tell me about yourself.',
      question_number: 1,
      total_questions: 5,
      stage: 'intro',
      warm_up_source: 'bank',
      domain: 'ml_genai',
      audio_b64: '',
    })
    mocks.respond('/api/session/s1/answer', {}, false, 500)
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /start interview/i }))
    await screen.findByText('Tell me about yourself.')

    await userEvent.type(screen.getByPlaceholderText('Type here'), 'my answer')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByRole('button', { name: /dismiss/i })).toBeInTheDocument())
    expect(screen.queryByText('my answer')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 8: Run the tests and see them pass**

```bash
cd frontend && npm test
```

Expected: 3 passed. If the third fails, do NOT change the test — it encodes the optimistic-rollback guard at `App.jsx:329`. Report a mismatch instead.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/src/test frontend/src/App.test.jsx
git commit -m "Add Vitest and characterization tests for the frontend"
```

---

### Task 2: Extract the leaf components

**Files:**
- Create: `frontend/src/lib/audio.js`, `frontend/src/components/ScoreRow.jsx`, `frontend/src/components/ErrorBanner.jsx`, `frontend/src/components/Transcript.jsx`, `frontend/src/components/Composer.jsx`, `frontend/src/components/Transcript.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Produces:
  - `playAudio(audioB64, setStatus): Promise<void>` — default export absent; named export.
  - `<ScoreRow label={string} value={number|null} />`
  - `<ErrorBanner error={string|null} onDismiss={fn} />` — renders nothing when `error` is falsy.
  - `<Transcript history={Array<{role,content}>} done={boolean} endRef={ref} status={string} />`
  - `<Composer value={string} onDraftChange={fn} onSubmit={fn} status={string} placeholder={string} onStartRecording={fn} onStopRecording={fn} />`

- [ ] **Step 1: Create `src/lib/audio.js`**

Move the body of `playAudio` (`App.jsx:185-190`) verbatim, taking `setStatus` as a second argument:

```js
export async function playAudio(audioB64, setStatus) {
  setStatus('speaking')
  const audio = new Audio(`data:audio/mp3;base64,${audioB64}`)
  audio.onended = () => setStatus('idle')
  await audio.play()
}
```

- [ ] **Step 2: Create `src/components/ScoreRow.jsx`**

Move `App.jsx:28-46` verbatim, including the comment above it. Export it as a named export AND keep the same JSX exactly — the `role="meter"` attributes were added deliberately for screen readers.

- [ ] **Step 3: Create `src/components/ErrorBanner.jsx`**

The banner markup currently appears twice in `App.jsx` identically. One component:

```jsx
export function ErrorBanner({ error, onDismiss }) {
  if (!error) return null
  return (
    <div className="banner">
      <span>{error}</span>
      <button type="button" onClick={onDismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Create `src/components/Transcript.jsx`**

Move the `history.map` block and the `chatEndRef` sentinel div. The `done` prop drives the `wrap-up` class on the last turn, exactly as today:

```jsx
export function Transcript({ history, done, endRef, status }) {
  return (
    <div className="messages">
      {history.map((m, i) => (
        <div
          key={i}
          className={`turn ${m.role}${done && i === history.length - 1 ? ' wrap-up' : ''}`}
        >
          <span className="turn-label">{m.role === 'user' ? 'You' : 'Interviewer'}</span>
          <p className="turn-text">{m.content}</p>
        </div>
      ))}
      {(status === 'thinking' || status === 'transcribing') && (
        <p className="hint">{status}…</p>
      )}
      <div ref={endRef} />
    </div>
  )
}
```

- [ ] **Step 5: Create `src/components/Composer.jsx`**

Move the `<form className="composer">` block verbatim, parameterised:

```jsx
export function Composer({
  value,
  onDraftChange,
  onSubmit,
  status,
  placeholder,
  onStartRecording,
  onStopRecording,
}) {
  return (
    <form onSubmit={onSubmit} className="composer">
      <input
        value={value}
        onChange={(e) => onDraftChange(e.target.value)}
        placeholder={placeholder}
        disabled={status === 'thinking'}
      />
      <button type="submit" disabled={status === 'thinking' || !value.trim()}>
        Send
      </button>
      {status === 'recording' ? (
        <button type="button" className="recording" onClick={onStopRecording}>
          ⏹ Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={onStartRecording}
          disabled={status !== 'idle'}
          aria-label="Answer by voice"
        >
          🎤
        </button>
      )}
    </form>
  )
}
```

- [ ] **Step 6: Rewire `App.jsx`**

Delete the moved code, import the five new modules, and render them with the props above. Replace both inline banners with `<ErrorBanner error={error} onDismiss={() => setError(null)} />` — keeping each in its current position. Replace `playAudio(x)` calls with `playAudio(x, setStatus)` and delete the local function.

- [ ] **Step 7: Write a test for `Transcript`**

`frontend/src/components/Transcript.test.jsx`:

```jsx
import { render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { describe, expect, it } from 'vitest'
import { Transcript } from './Transcript'

const history = [
  { role: 'assistant', content: 'First question' },
  { role: 'user', content: 'My answer' },
]

describe('Transcript', () => {
  it('labels each turn by speaker', () => {
    render(<Transcript history={history} done={false} endRef={createRef()} status="idle" />)
    expect(screen.getByText('Interviewer')).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
  })

  it('marks only the last turn as the wrap-up when the session is done', () => {
    const { container } = render(
      <Transcript history={history} done endRef={createRef()} status="idle" />
    )
    const turns = container.querySelectorAll('.turn')
    expect(turns[0].className).not.toContain('wrap-up')
    expect(turns[1].className).toContain('wrap-up')
  })

  it('shows a pending hint only while thinking or transcribing', () => {
    const { rerender } = render(
      <Transcript history={history} done={false} endRef={createRef()} status="idle" />
    )
    expect(screen.queryByText('thinking…')).not.toBeInTheDocument()
    rerender(<Transcript history={history} done={false} endRef={createRef()} status="thinking" />)
    expect(screen.getByText('thinking…')).toBeInTheDocument()
  })
})
```

- [ ] **Step 8: Verify nothing changed**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected: 6 passed (3 characterization + 3 Transcript), lint clean, build clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "Extract the leaf components and the audio helper"
```

---

### Task 3: Extract the screen-level components

**Files:**
- Create: `frontend/src/components/StartScreen.jsx`, `frontend/src/components/CodingWorkspace.jsx`, `frontend/src/components/Evaluation.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Produces:
  - `<StartScreen apiReady, status, error, onDismissError, resumeName, resumeStatus, onResumeChange, resumeId, fallbackOffer, onStartInterview, onCancelFallback />`
  - `<CodingWorkspace dsa, code, onCodeChange, running, status, onRun, onSubmit, runReport />`
  - `<Evaluation evaluation />`

- [ ] **Step 1: Create `StartScreen.jsx`**

Move `App.jsx:474-583` (the whole `if (screen === 'start')` return body) verbatim into the component, replacing each piece of state with the prop of the same name and each handler with its prop. `onStartInterview` takes the `allowBankFallback` boolean the current code passes. Keep every string exactly as it is — the copy was settled in PR 1.

- [ ] **Step 2: Create `CodingWorkspace.jsx`**

Move the `.dsa-pane` block verbatim, including the `CodeMirror` element and its `python()` extension. The `@uiw/react-codemirror` and `@codemirror/lang-python` imports move here and leave `App.jsx`.

- [ ] **Step 3: Create `Evaluation.jsx`**

Move the `.evaluation` block verbatim. It imports `ScoreRow` from Task 2. Keep every conditional — `q.skipped`, `q.unscored`, the `hints`/`runs` line, the coverage line — exactly as written; each represents an evaluator state that the backend really produces (ADR 0011/0020).

- [ ] **Step 4: Rewire `App.jsx`**

`App.jsx` should now contain: state and refs, the six effects, the handler functions, and a compact render tree. It should be roughly 400 lines.

- [ ] **Step 5: Verify**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected: 6 passed, lint clean, build clean. If a characterization test fails, the extraction changed behaviour — fix the extraction, never the test.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "Extract the start, coding and evaluation screens into components"
```

---

### Task 4: Extract the three independent hooks

**Files:**
- Create: `frontend/src/hooks/useVoices.js`, `frontend/src/hooks/useApiReady.js`, `frontend/src/hooks/useEvaluation.js`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Produces:
  - `useVoices(onError) -> { voices, voice, setVoice }`
  - `useApiReady() -> boolean`
  - `useEvaluation({ phase, sessionId, onError }) -> { evaluation, evaluating, resetEvaluation }`

- [ ] **Step 1: `useVoices.js`**

Move `App.jsx:82-90`. The catch currently calls `setError('backend not reachable — is it running on port 8000?')`; that exact string moves to `onError(...)`.

```js
import { useEffect, useState } from 'react'
import { api } from '../api'

export function useVoices(onError) {
  const [voices, setVoices] = useState({})
  const [voice, setVoice] = useState('')

  useEffect(() => {
    fetch(api('/api/voices'))
      .then((r) => r.json())
      .then((data) => {
        setVoices(data.voices)
        setVoice(data.default)
      })
      .catch(() => onError('backend not reachable — is it running on port 8000?'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { voices, voice, setVoice }
}
```

The empty dependency array is deliberate and matches today's behaviour: this fetch runs once. Adding `onError` to the deps would re-run it on every render unless the caller memoises. Keep the disable comment so the next reader knows it was considered.

- [ ] **Step 2: `useApiReady.js`**

Move `App.jsx:92-111` including its entire four-paragraph comment block — it explains why there is no timeout and why only a 2xx counts (ADR 0025). That comment is the most load-bearing in the file.

- [ ] **Step 3: `useEvaluation.js`**

Move `App.jsx:118-142` verbatim, including the `AbortController` and the `if (!controller.signal.aborted)` guard in the `finally`. Add a `resetEvaluation()` that sets `evaluation` to `null` and `evaluating` to `false`, for `startNewInterview` to call.

- [ ] **Step 4: Rewire and verify**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected: 6 passed, lint clean (note `react/rules-of-hooks` is an error-level rule and will catch a mis-extracted hook), build clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "Extract the voices, health-ping and evaluation hooks"
```

---

### Task 5: Extract the résumé upload and recorder hooks

**Files:**
- Create: `frontend/src/hooks/useResumeUpload.js`, `frontend/src/hooks/useRecorder.js`, `frontend/src/hooks/useRecorder.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Produces:
  - `useResumeUpload({ onError }) -> { resumeId, resumeName, resumeStatus, handleResumeChange }`
  - `useRecorder({ sessionId, setStatus, onError, onTranscript }) -> { startRecording, stopRecording }`

- [ ] **Step 1: `useResumeUpload.js`**

Move `App.jsx:262-292` verbatim. The `resumeUploadTokenRef` and BOTH of its `if (token !== resumeUploadTokenRef.current) return` guards move with it — they exist so a slow first upload cannot overwrite a faster second one. The catch must keep `setResumeName('')` (added in PR 1 so a failed upload cannot leave a stale filename on screen).

Deliberately does NOT expose a reset: `startNewInterview` keeps the uploaded résumé so a second interview needs no re-upload. That is existing behaviour and the comment at `App.jsx:241` explains it — move that comment to whichever code still carries the decision.

- [ ] **Step 2: `useRecorder.js`**

Move `App.jsx:378-466` verbatim — `startRecording`, `stopRecording` and `recorderRef`. Move the three constants `SPEECH_PEAK_THRESHOLD`, `MIN_RECORDING_MS`, `MIN_TRANSCRIPT_CHARS` and their comment block, which records the measurement that justifies the threshold. `sendTranscript(data.transcript)` becomes `onTranscript(data.transcript)`.

- [ ] **Step 3: Write the failing tests**

`frontend/src/hooks/useRecorder.test.jsx`. These pin the two guards that stop Whisper hallucinating an answer out of silence:

```jsx
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useRecorder } from './useRecorder'

function setup({ peak }) {
  const mocks = installMocks({ peak })
  const onTranscript = vi.fn()
  const onError = vi.fn()
  const setStatus = vi.fn()
  const { result } = renderHook(() =>
    useRecorder({ sessionId: 's1', setStatus, onError, onTranscript })
  )
  return { mocks, onTranscript, onError, setStatus, result }
}

describe('useRecorder', () => {
  beforeEach(() => vi.useRealTimers())

  it('refuses a clip that captured no speech', async () => {
    const { mocks, onTranscript, onError, result } = setup({ peak: 0 })
    mocks.respond('/api/transcribe', { transcript: 'Thank you.' })
    await act(async () => {
      await result.current.startRecording()
    })
    await new Promise((r) => setTimeout(r, 1100))
    await act(async () => {
      result.current.stopRecording()
    })
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0][0]).toMatch(/didn't catch that/i)
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('refuses a clip that was too short even when speech was heard', async () => {
    const { onTranscript, onError, result } = setup({ peak: 0.5 })
    await act(async () => {
      await result.current.startRecording()
    })
    await act(async () => {
      result.current.stopRecording()
    })
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0][0]).toMatch(/too short/i)
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('sends a clip that had speech and lasted long enough', async () => {
    const { mocks, onTranscript, result } = setup({ peak: 0.5 })
    mocks.respond('/api/transcribe', { transcript: 'a real answer' })
    await act(async () => {
      await result.current.startRecording()
    })
    await new Promise((r) => setTimeout(r, 1100))
    await act(async () => {
      result.current.stopRecording()
    })
    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith('a real answer'))
  })

  it('reports a permission refusal without starting a recording', async () => {
    const { onError, setStatus, result } = setup({ peak: 0.5 })
    globalThis.navigator.mediaDevices.getUserMedia = vi.fn(async () => {
      throw new Error('denied')
    })
    await act(async () => {
      await result.current.startRecording()
    })
    expect(onError.mock.calls[0][0]).toMatch(/microphone permission denied/i)
    expect(setStatus).not.toHaveBeenCalledWith('recording')
  })
})
```

- [ ] **Step 4: Run them**

```bash
cd frontend && npm test -- useRecorder
```

Expected: 4 passed. If the level-timer polling makes the peak read zero, the fake's `getByteTimeDomainData` is not being called — check that the hook still creates the analyser before `recorder.start()`.

- [ ] **Step 5: Rewire and verify everything**

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected: 10 passed, lint clean, build clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "Extract the resume upload and recorder hooks"
```

---

### Task 6: Extract the coding-round and session hooks

The last and hardest extraction. These two share `applyProgress`.

**Files:**
- Create: `frontend/src/hooks/useDsaRound.js`, `frontend/src/hooks/useSession.js`, `frontend/src/hooks/useDsaRound.test.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Produces:
  - `useSession({ voice, resumeId, setStatus, onError }) -> { screen, sessionId, history, phase, stage, questionNumber, totalQuestions, sessionDomain, warmUpSource, fallbackOffer, setFallbackOffer, latencyMs, dsa, startInterview, startNewInterview, sendTranscript, applyProgress, appendAssistant }`
  - `useDsaRound({ sessionId, voice, dsa, questionNumber, statusRef, setStatus, onError, appendAssistant, applyProgress }) -> { code, setCode, runReport, dsaSubmitted, running, runCode, submitCode }`

- [ ] **Step 1: `useSession.js`**

Move `App.jsx:192-333` — `startInterview`, `startNewInterview`, `applyProgress`, `sendTranscript` — and the state they own. Keep verbatim:
- the 409 branch in `startInterview` and its comment (a 409 is the backend asking whether a general interview is acceptable, ADR 0023, not an error)
- the `apiReady`-aware catch message (ADR 0025)
- `setHistory(history)` in `sendTranscript`'s catch — the optimistic rollback the characterization test pins
- the `data.question_number !== questionNumber` guard in `applyProgress` and its comment (ADR 0019: a coding-chat reply carries the same question's payload, so the editor must not reset)

`appendAssistant(content)` is a new one-line helper — `setHistory((h) => [...h, { role: 'assistant', content }])` — so the check-in poll and `submitCode` can add a turn without owning history.

`startNewInterview` must NOT own evaluation state. `App.jsx` calls both, in this order:

```jsx
function handleNewInterview() {
  session.startNewInterview()
  resetEvaluation()
}
```

That is the handler passed to the "Start new interview" button.

- [ ] **Step 2: `useDsaRound.js`**

Move `App.jsx:144-183` (the snapshot effect and the check-in poll) and `335-376` (`runCode`, `submitCode`), plus `SNAPSHOT_DEBOUNCE_MS` and `CHECK_IN_POLL_MS` and their comment.

Three things must survive exactly:
- `code === dsa.starter_code` in the snapshot effect's guard. Posting untouched starter code would falsely start the watcher's typing clock and permanently foreclose the Offer for a Candidate who never typed (ADR 0018).
- `if (statusRef.current !== 'idle') return` at the top of the poll, and the second `if (statusRef.current === 'idle')` before playing audio — the interviewer must never talk over the Candidate.
- the empty `catch {}` with its comment: a failed check-in is a silent one.

The editor reset on a new question stays driven by `dsa` and `questionNumber` exactly as `applyProgress` does it today.

- [ ] **Step 3: Write the failing tests**

`frontend/src/hooks/useDsaRound.test.jsx`:

```jsx
import { act, renderHook, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMocks } from '../test/mocks'
import { useDsaRound } from './useDsaRound'

const dsa = {
  function_name: 'two_sum',
  signature: 'def two_sum(nums, target):',
  starter_code: 'def two_sum(nums, target):\n    pass\n',
  test_cases: [],
}

function setup(mocks) {
  const statusRef = createRef()
  statusRef.current = 'idle'
  const appendAssistant = vi.fn()
  const applyProgress = vi.fn()
  const { result } = renderHook(() =>
    useDsaRound({
      sessionId: 's1',
      voice: 'v1',
      dsa,
      questionNumber: 1,
      statusRef,
      setStatus: vi.fn(),
      onError: vi.fn(),
      appendAssistant,
      applyProgress,
    })
  )
  return { result, appendAssistant, applyProgress, statusRef }
}

describe('useDsaRound', () => {
  let mocks
  beforeEach(() => {
    vi.useFakeTimers()
    mocks = installMocks()
  })

  it('does not snapshot untouched starter code', async () => {
    setup(mocks)
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    const snapshots = mocks.calls.filter((c) => c.path.includes('/dsa/snapshot'))
    expect(snapshots).toHaveLength(0)
  })

  it('snapshots once the Candidate has actually typed', async () => {
    mocks.respond('/dsa/snapshot', {})
    const { result } = setup(mocks)
    act(() => {
      result.current.setCode(dsa.starter_code + '    return []\n')
    })
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })
    const snapshots = mocks.calls.filter((c) => c.path.includes('/dsa/snapshot'))
    expect(snapshots).toHaveLength(1)
  })

  it('adds no turn when the interviewer stays silent', async () => {
    mocks.respond('/dsa/check-in', { action: 'silent' })
    const { appendAssistant } = setup(mocks)
    await act(async () => {
      vi.advanceTimersByTime(26000)
    })
    expect(appendAssistant).not.toHaveBeenCalled()
  })

  it('adds a turn when the interviewer checks in', async () => {
    mocks.respond('/dsa/check-in', { action: 'nudge', remark: 'How is it going?', audio_b64: '' })
    const { appendAssistant } = setup(mocks)
    await act(async () => {
      vi.advanceTimersByTime(26000)
    })
    await waitFor(() => expect(appendAssistant).toHaveBeenCalledWith('How is it going?'))
  })

  it('does not poll while the Candidate is speaking', async () => {
    mocks.respond('/dsa/check-in', { action: 'nudge', remark: 'x', audio_b64: '' })
    const { statusRef, appendAssistant } = setup(mocks)
    statusRef.current = 'recording'
    await act(async () => {
      vi.advanceTimersByTime(26000)
    })
    expect(appendAssistant).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 4: Run them**

```bash
cd frontend && npm test -- useDsaRound
```

Expected: 5 passed.

- [ ] **Step 5: Rewire `App.jsx` and verify everything**

`App.jsx` should now be roughly 120 lines: `status`, `statusRef`, `error`, `draft`, `screen` routing, seven hook calls, and the render tree.

```bash
cd frontend && npm test && npm run lint && npm run build
```

Expected: 15 passed, lint clean, build clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "Extract the coding-round and session hooks"
```

---

### Task 7: Verify the refactor changed nothing, and open the PR

**Files:** none modified.

- [ ] **Step 1: Confirm no behaviour drifted**

```bash
cd frontend && npm test && npm run lint && npm run build
cd ../backend && .venv/Scripts/python -m pytest -q
```

Expected: 15 frontend tests passed, lint clean, build clean, 322 backend tests passed.

- [ ] **Step 2: Confirm the ADR comments survived the move**

```bash
grep -rn "ADR 00" frontend/src --include=*.js --include=*.jsx
```

Expected: references to ADRs 0018, 0019, 0023, 0025 and 0026 all still present, each beside the code it explains. A missing one means a comment was dropped during extraction — restore it from `git show feat/callback-rename-visual-system:frontend/src/App.jsx`.

- [ ] **Step 3: Confirm the shape of the result**

```bash
wc -l frontend/src/App.jsx frontend/src/hooks/*.js frontend/src/components/*.jsx
```

Expected: `App.jsx` well under 200 lines; no single hook or component over ~150.

- [ ] **Step 4: Confirm no user-visible string changed**

```bash
git diff feat/callback-rename-visual-system..HEAD -- frontend/src | grep -E '^[-+].*"[A-Z]' | grep -v import
```

Read the output. Every string that appears with `-` should appear again with `+` somewhere — moved, not reworded. Any string that only appears on one side is a copy change and must be reverted.

- [ ] **Step 5: Push and open the PR**

```bash
git push -u origin feat/callback-component-extraction
gh pr create --base feat/callback-rename-visual-system --head feat/callback-component-extraction \
  --title "Split App.jsx into hooks and components behind a test suite (PR 2)" --body-file -
```

Base is PR 1's branch, not `main`, because PR 1 is still open. GitHub retargets it to `main` automatically when #46 merges.

The body covers: what moved where, the seam decision about `status` and `error` staying in `App.jsx`, the test suite added, and explicit confirmation that no behaviour changed. No Claude or Anthropic attribution.

- [ ] **Step 6: Report briefly**

Per repo convention: the PR link, one line on what it does, test status, anything needing a decision.

---

## Out of scope

- **PR 3** — `DsaPayload.prompt`, `CodingWorkspace`'s pinned question, `InterviewerRail`, the `.wrap--wide` layout mode, the run-results table.
- The section icons, still being regenerated white-on-transparent.
- The `og:image` absolute URL, blocked on the deploy domain existing.
- Any behaviour fix. Defects found during extraction get recorded in the task report and left alone.
