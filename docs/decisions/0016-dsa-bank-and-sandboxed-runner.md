# ADR 0016: DSA round part 1 — extended question bank and sandboxed runner

Date: 2026-07-17 · Status: accepted

## Context

ADR 0012 defined the DSA round: 2 curated coding questions, Python only,
run against per-question test cases in a sandboxed subprocess. This ADR
records the shape of the bank and the runner's sandbox posture. The
interview-flow half (submit, reaction, discussion) is ADR 0017.

## Decision

**Bank.** `dsa.yaml` is a standalone bank (`domain: dsa`), not per-domain:
every interview domain shares one coding round. Entries extend the ADR 0003
schema with `function_name`, `signature`, `starter_code`, and `test_cases`
(each case `{args, expected}`, JSON values, exactly one correct output —
the runner compares with `==`). A separate `DsaQuestion` dataclass keeps
the extra fields mandatory; widening `Question` with optionals would let a
half-authored entry pass validation. `plan_dsa` draws 1 easy + 1
medium-or-hard, seeded.

**Runner.** Candidate code runs via `sys.executable -I` in a temp-dir cwd
with a hard timeout (5 s) and a scrubbed environment — the backend process
holds API keys and candidate code can read `os.environ`, so only the
variables the Python runtime needs cross the boundary. The harness writes
per-case results to `results.json` (candidate prints cannot corrupt the
parse) and normalizes returns through a JSON round-trip (a tuple matches a
list-shaped expected). Distinct statuses: `ok` (cases ran), `error` (code
never loaded / function missing), `timeout`.

## Options considered for isolation

1. In-process `exec` with signal timeouts — rejected: one infinite loop
   hangs the event loop; `signal` alarms don't exist on Windows.
2. Subprocess with limits (chosen) — portable, kills runaway code, scrubs
   secrets; no network/memory caps without OS-specific machinery.
3. Containers/jails — real isolation, but heavy for a self-hosted demo
   tool; deferred to a hardening day per ADR 0012.

## Consequences

- The sandbox stops accidents and casual mischief (key theft via env,
  server hangs, print pollution), not a determined attacker. Documented
  best-effort; the app stays a run-it-yourself tool (ADR 0001).
- No network blocking: candidate code can make HTTP calls. Accepted until
  the hardening day.
- Each run costs a process spawn (~0.3–1 s on Windows) — fine per click,
  and the test suite slows by ~10–20 s because the subprocess is the unit
  under test.
- Bank authoring rule: single deterministic correct output per case. A
  future judge-based comparator (for multiple-valid-answer questions) is
  the named upgrade if the bank needs richer problems.
