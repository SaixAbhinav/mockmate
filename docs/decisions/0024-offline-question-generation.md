# ADR 0024: Question banks are generated offline, gated by machine, reviewed by hand

Date: 2026-07-23 · Status: proposed

## Context

The banks are too small to hide it. `ml_genai.yaml` holds 16 questions and
`dsa.yaml` holds 6 — three easy, two medium, one hard. Since `plan_dsa` draws
one easy and one medium-or-hard (`questions.py:168`), the coding round has
exactly **nine possible pairs**: a Candidate doing three Sessions will almost
certainly be asked a coding question twice. The warm-up fallback draws 3 of 16,
so it exhausts nearly as fast.

[ADR 0003](0003-question-banks-open-source-curated.md) chose "seed from
permissively-licensed open collections, normalize into our YAML schema, then
expand with LLM assistance under human review," and
[ADR 0008](0008-question-source-curated-yaml.md) scoped v1 to ~15 hand-written
ML questions. **The ingestion half was never built.** There is no `scripts/`
directory, no importer, no normalizer — `backend/` contains only `app` and
`tests`. Every one of the 22 questions in the repo was typed into YAML by a
person. That is the real reason the banks are small, and no amount of retrieval
or matching logic fixes a bank that doesn't exist yet.

Meanwhile [ADR 0015](0015-resume-grounded-warm-up.md) already ships
LLM-generated questions straight to Candidates at Session creation, with **no
human in the loop at all**. So the repo's current posture is inconsistent: the
questions a human wrote are the small, slow-growing ones, and the questions
nobody reviewed are the ones most Candidates actually hear.

ADR 0003 framed the choice as three options — scrape, LLM-generate everything,
or curate. There is a fourth it didn't separate out, and it is materially
different from the second: **generate offline, verify what a machine can
verify, review the rest by hand, and commit the survivors as YAML.** The
distinction is *when* vetting happens. Runtime generation is unvetted by
construction. Build-time generation is vetted exactly once, permanently, before
any Candidate sees it.

## Decision

**Bank expansion becomes an offline pipeline** — a script under
`backend/scripts/`, importing from `app` but never imported by it. It is a
dev-time chore, not an endpoint and not part of the running service. It writes
to a staging file and **never edits a bank YAML directly**.

**Generation is driven by topic quota, not bulk.** The script asks for a
specific count on a specific `topic`, passing the existing bank entries for
that topic as few-shot examples and as explicit "do not overlap these"
context. Two reasons: the 16 hand-written questions are the house style
reference (spoken length, `follow_up_hints` phrasing, tone), and open-ended
bulk requests converge — ask for 200 questions and a meaningful fraction are
rewordings of each other. Coverage is something we steer, not something we
hope for.

**A machine gate runs before any human looks at anything.** Candidates that
fail are dropped and regenerated, never surfaced:

- **Schema** — run the staging file through `load_bank` / `load_dsa_bank`,
  which already fail fast on malformed entries (`questions.py:30`). No new
  validation code.
- **Spoken length** — questions are read aloud by TTS (ADR 0004); the
  generation prompts already cap around 30 words and models routinely exceed
  it.
- **Duplication** — against the existing bank and within the batch, on
  question text.
- **Coding-question correctness, via the runner.** The generator must also
  emit a `reference_solution`. The script runs
  `run_tests(reference_solution, function_name, test_cases)`
  (`runner.py:99` — already sandboxed, already synchronous, already takes
  exactly these fields) and rejects the question unless every case passes.
  **The reference solution is then discarded**; it exists to prove the question
  is coherent and never enters the bank.

That last check is the one that earns this ADR. It catches wrong `expected`
values, signatures that contradict the prose, and questions whose description
asks for something different from what the tests assert — exactly the failure
class a human reviewer skims straight past.

**The human stage is deletion, not authorship.** Survivors land in the staging
YAML; the reviewer deletes the bad, lightly edits the mediocre, and moves the
keepers into the real bank. Judging a question costs seconds where writing one
costs minutes, and that ratio is the entire argument for this pipeline.

**The bank YAML remains the single source of truth**, and the staging file is
gitignored. Generation is not reproducible and does not need to be — nobody
re-runs the script to reconstruct a bank; they read the diff in the PR. The
reviewed YAML is the artifact.

## Consequences

- **Vetting moves from never to once.** Today ADR 0015's runtime questions
  reach a Candidate unreviewed. A generated-then-reviewed bank entry is checked
  once and is then permanent. A bad question costs a keystroke instead of
  costing someone their interview.
- **The runner gate covers coding questions only.** For conceptual warm-up
  questions there is nothing machine-checkable — a question can be well-formed,
  correctly scoped, on-topic, and still boring or subtly wrong. The quality
  floor rises sharply for DSA and only modestly elsewhere. Stated plainly so
  the pipeline isn't mistaken for a quality guarantee it can't give.
- **Review time becomes the real bottleneck**, and it is the owner's time. ADR
  0003 called human review "a standing chore"; this makes that literal and
  measurable. The pipeline's value is entirely in how much it raises questions
  reviewed per hour.
- **Discarding reference solutions means the correctness proof isn't kept.** If
  a committed test case is later suspected wrong, there is no stored artifact
  showing it once passed — it has to be re-derived. Accepted: keeping solutions
  in the repo alongside their questions is a worse problem (they are answers to
  questions Candidates are about to be asked).
- **Convergence is mitigated, not solved.** Topic quotas and text dedupe catch
  near-identical questions; they do not catch two questions that probe the same
  idea in different words. Watch for it in review.
- **Offline generation spends provider quota** (ADR 0002's free tiers). It is
  off the conversational critical path, so slowness doesn't matter, but rate
  limits still bound how fast a batch runs.
- **No new dependency.** It reuses `providers.py`, `runner.py`, and pyyaml.
  Chroma stays deferred — this ADR is about *having* questions; retrieval and
  matching are about *choosing* them, and that decision stays open.
- **ADR 0015's runtime generation is unchanged and still unvetted.** A bigger
  bank makes the fallback path better, not the resume path. If runtime
  generation should also be gated, that is a separate decision.

## Alternatives considered

- **Keep hand-writing questions.** The status quo, and the evidence against it
  is the repo: 22 questions across the whole project's history. Retrieval, more
  domains, and a longer Session all need an order of magnitude more.
- **Scrape interview-prep sites.** Already rejected by ADR 0003 on licensing
  and quality; nothing has changed.
- **Generate at runtime and cache what looks good.** Rejected: the first
  Candidate to receive a bad question is the reviewer, which is precisely the
  cost this ADR exists to avoid.
- **Skip the runner gate and review coding questions by hand.** Rejected on
  evidence rather than principle — verifying `expected` outputs by reading is
  slow and unreliable, and the sandboxed runner that does it perfectly is
  already built and already tested (`test_runner.py`).
