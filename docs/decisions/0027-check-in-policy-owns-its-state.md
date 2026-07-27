# ADR 0027: The check-in policy owns its own state

Date: 2026-07-27 · Status: proposed

## Context

ADR 0018 decided that **the backend owns the check-in policy** — the frontend
polls, the server's gates decide what a poll becomes, so a misbehaving client
cannot farm LLM calls. That decision holds and is not in question here. What is
in question is *where inside the backend* the policy lives.

`backend/app/watcher.py` opens by saying it lives there:

> the endpoints supply the clock, these functions decide

That split was never built. `watcher.py` supplies **predicates**; `main.py`
**decides**. The sequencing that constitutes the policy — Offer first, else a
look if due, else silence; record the look even when the Provider failed; count
a Hint but not an Offer — is 48 lines of the `dsa_check_in` endpoint
(`main.py:657-704`), not of `watcher.py`.

This is the same shape as ADR 0021: an interface an earlier ADR treated as
existing, which on inspection did not. That one built the store interface ADR
0007 promised; this one builds the policy interface `watcher.py`'s own docstring
promises.

**The measurements.** Taken from `main` at the time of writing:

| | Count | Where |
|---|---|---|
| Names imported from `watcher` into `main.py` | 13 | `main.py:44` |
| Public names `watcher.py` defines | 17 | 10 functions, 7 constants |
| Copies of `question.get("watch") or start_watch(now)` | 4 | `main.py:519`, `:596`, `:652`, `:667` |
| `_store_watch(...)` write-back calls | 7 | throughout `main.py` |
| Raw `watch[...]` key reads in `main.py` | 4 | `:520`, `:521`, `:679`, `:686` |
| Raw `watch[...]` key reads in `agent.py` | 4 | `:196-199`, building the evaluator record |
| Lines in `dsa_check_in` | 48 | `main.py:657-704` |

`watcher.py` is 152 lines and its largest function is 13. A 17-name interface
over an implementation that thin is a shallow module: a caller learns nearly as
much by reading the interface as it would by inlining the code.

**The testability tell.** `tests/test_watcher.py` has 18 tests and every one
exercises a single predicate — `offer_due`, `check_in_due`, `is_stuck`,
`note_*`. Not one tests the policy, because the policy is not in the module. It
is covered only end-to-end through a FastAPI `TestClient` in `test_main.py`. The
behaviour most worth testing directly has no direct test surface.

**Why this is more than tidiness.** Lazy watch creation is an invariant of the
Watcher, written out four times in the endpoint layer; the next endpoint to
touch a watch is the one that forgets it. The raw dict shape is likewise part of
the interface — `agent.py` indexes `interjections`/`hints`/`chats`/`runs`
directly to build the record ADR 0020 scores from — so renaming one key inside
`watcher.py` is a three-module change today.

**Vocabulary.** This ADR uses `CONTEXT.md`'s corrected terms: a **Check-in** is
the Watcher *looking* at a Snapshot and is usually silent; an **Interjection** is
the Watcher *speaking*, in one of three kinds (Offer, Ask, Hint). The glossary
previously defined Check-in as the speaking, contradicting the code; the code's
meaning won, because the policy — interval, cooldown, cap — attaches to looking.

## Decision

**Move the check-in decision into `watcher.py`, and let it take the Provider as
an argument.** `main.py` learns five names where it currently learns thirteen.

- **`async def check_in(watch, *, question_text, starter_code, now, provider) -> tuple[dict, CheckIn]`**
  — the whole policy behind one call. It absorbs the Offer-before-look ordering,
  both due gates, the stuck computation, the run summary, the `watch_code` call,
  the rule that a Provider failure answers *silent*, the rule that the look is
  recorded even on failure so a failing Provider is not hammered on the next
  poll, and Interjection/Hint counting. `CheckIn` is a frozen dataclass of
  `action` and `remark`, mirroring `WatchDecision`.

- **`def observe_snapshot(...)` / `def observe_run(...)`** — the two events the
  endpoints genuinely originate, renamed from `record_snapshot` / `note_run` for
  consistency.

- **`def tally(watch) -> dict`** — the Interjection/Hint/chat/run counts
  `agent.py` needs for the evaluator record, so it stops indexing raw keys.

**`check_in` takes scalars, not the Question.** Today `watcher.py` knows nothing
about a Question's shape — `is_stuck(watch, starter_code)` takes a string, and
the module contains no `question[...]` access at all. Passing the question dict
would be more convenient and would newly couple the Watcher to `agent.py`'s
state shape, which is the exact kind of coupling this ADR exists to remove. Four
keyword arguments is the right price for keeping the module ignorant of who
stores its state.

**Lazy creation and write-back move to `agent.py`, not `watcher.py`** — for the
same reason. `question["watch"]` and `_store_watch` are operations on
`InterviewState`, and `agent.py` owns `InterviewState`. Two additions there —
`current_watch(state, now)` and `set_watch(state, watch)` — delete `main.py`'s
`_store_watch` and all four lazy-creation copies. `agent.py` gains an import of
`watcher.start_watch`; `watcher` imports nothing from `agent`, so no cycle.

**What deliberately stays out.** The Watcher never touches `InterviewState`. It
returns a decision; `main.py` still calls `record_interjection`, still saves,
still synthesises audio, still raises `HTTPException`. The seam is: **watcher
owns watch state and check-in policy, agent owns interview state, main owns
transport.** A watcher that also spoke and persisted would be a fat module, not
a deep one.

**ADR 0018's purity benefit is preserved.** That ADR justified pure functions
because "cooldown rules are one-line unit tests." The predicates — `offer_due`,
`check_in_due`, `is_stuck` — stay pure, sync, and module-level. They simply stop
being part of what `main.py` must know: they become internal seams, still
directly tested by `test_watcher.py`, no longer part of the external interface.
Only `check_in` is `async`, and only because it calls a Provider.

**No behaviour changes.** Every gate, cooldown, cap, remark and counter keeps its
current semantics. This is a relocation, and `test_main.py`'s existing
end-to-end coverage is what proves it.

## Consequences

- **`watcher.py` gains a dependency on `providers.py`.** Accepted as an
  argument, never constructed, so the module stays testable without patching and
  `ScriptedProvider` is already the fake. This is the trade that buys everything
  else and it is worth naming plainly: `watcher.py` is I/O-free today and will
  not be afterwards.

- **The check-in policy gets direct tests for the first time.** Offer-beats-look
  ordering, silence-on-provider-failure, and look-recorded-anyway are currently
  asserted only through HTTP. They become ordinary function tests. The new tests
  are as much the deliverable as the move is.

- **`main.py` loses roughly 40 lines**, and `dsa_check_in` drops from 48 lines to
  fetch / decide / persist / speak.

- **Renaming a watch key becomes a one-module change**, down from three.

- **`test_agent.py` and `test_main.py` import watcher internals** to build watch
  dicts. They keep working, but tests reaching for `start_watch` should move to
  `agent.current_watch` as they are touched, or the old idiom will quietly
  outlive its removal from the app.

- **The watch stays a plain dict.** Making it a dataclass is tempting and is not
  part of this ADR — see alternatives.

- **This amends ADR 0018 rather than superseding it.** The policy is unchanged;
  only its address is.

## Deliberately not fixed here: chat does not start the interjection cooldown

Found while writing this ADR, recorded so it is not lost. `note_chat` increments
`chats` and touches nothing else; `check_in_due` gates on `last_spoke_at`, which
only `note_interjection` sets. So a spoken chat reply (ADR 0019) does **not**
start the 90-second cooldown between spoken things. The Interviewer can answer
the Candidate's question and then interject unprompted moments later — the
hovering failure mode ADR 0018 was written to prevent, via a path that postdates
it. The frontend skips polls while not idle (`App.jsx:142`), which narrows the
window without closing it, and ADR 0018 is explicit that the policy must be
server-enforced precisely so client behaviour cannot be relied on.

This ADR does not fix it, because this ADR is behaviour-preserving and mixing a
behaviour change into a relocation would destroy the one thing that makes the
relocation safe to review: that `test_main.py` passes unchanged. It belongs in
its own change, which `check_in` makes close to a one-line fix by giving the
rule somewhere to live.

## Alternatives considered

- **Do nothing.** Genuinely defensible: the feature works, it is covered
  end-to-end, and no bug has been traced to the structure. Rejected because an
  invariant written out four times is where the next endpoint's bug lands, and
  because "the policy has no direct test surface" is a cost that only comes due
  the day the policy changes — which the finding above says is soon.

- **Move `coding_chat`'s cap into `watcher` as well.** My first draft did this.
  Rejected: ADR 0019 states that chat's failure posture is *"deliberately unlike
  Check-ins (ADR 0018), which are automated polls and fail silent"* — chat is
  user-initiated, 503s, and leaves the Session untouched. Chat is a
  conversation, not watching. Housing both behind one module would assert a
  kinship two ADRs go out of their way to deny, for a leak of two imported
  names. If the chat cap ever moves, ADR 0019's own comparison points the way —
  it calls the cap "the same shape as the follow-up budget", and that budget
  lives in `agent.py`.

- **Pass the Question dict to `check_in`.** Fewer arguments, and it would couple
  `watcher` to `agent`'s state shape — creating exactly the cross-module
  key-knowledge this ADR is removing. Rejected on its own terms.

- **Make the watch a dataclass, leave the policy where it is.** Fixes the
  raw-key access, the smaller half of the problem, and fixes nothing about the
  policy: `main.py` would still sequence Offer / due / silent. Attractive later,
  behind the interface this ADR establishes; first would mean paying the
  serialisation churn without the payoff.

- **Move the entire endpoint body into `watcher.py`**, including
  `InterviewState`, TTS and HTTP mapping. Rejected: `watcher` would depend on
  `agent`, `tts` and FastAPI, and its tests would go straight back to needing a
  `TestClient`. Bigger is not deeper.

- **Fold Check-ins into the interview graph in `agent.py`.** Rejected on ADR
  0018's own terms: a Check-in is explicitly not a Turn — it never runs the
  graph, consumes no follow-up budget, and advances nothing. Putting it in the
  graph would blur a distinction two ADRs are built on.

- **A single `check_in_action()` helper inside `main.py`.** Cheapest change, and
  it does concentrate the sequencing — but it leaves the policy in the transport
  module, where its tests still need a `TestClient` and `watcher` still exports
  thirteen names. It moves the symptom.

## Status

Proposed. Behaviour-preserving by construction; the acceptance condition is that
`test_main.py` passes unchanged, plus new direct tests for the policy paths that
previously had none.
