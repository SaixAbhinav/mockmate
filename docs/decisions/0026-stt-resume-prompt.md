# ADR 0026: Bias transcription with a résumé-derived vocabulary digest

Date: 2026-07-26 · Status: proposed

## Context

Voice answers transcribe well for ordinary prose and badly for the words that
matter most: the Candidate's own name, their institution, and their project
names. From a real Session on the deployed app:

| Spoken | Transcribed |
|---|---|
| Sai Abhinav | "Saib", "Sai Abhinok" |
| Vivekananda Institute of Professional Studies | "Vivekan and the Institute of Professional Studies" |
| Workflow Copilot | "Workflow of Automation" |

This is ordinary Whisper weakness on proper nouns, not a defect — the model has
no way to know these strings. It matters more here than in most apps because the
warm-up round is *about* those projects (ADR 0015): the interviewer asks "what
was the goal of SmartSignal?" and the Candidate's answer naming SmartSignal comes
back mangled, so the judge sees an answer that appears not to address the
question.

A separate failure — Whisper inventing filler text from silence — was fixed
before this ADR by refusing to submit recordings that captured no speech. That
fix is load-bearing here, for reasons in Consequences.

**What already exists that this would use.** `POST /api/resume` stores extracted
résumé text in `_resumes`, keyed by `resume_id` (ADR 0015). Whisper's API accepts
a `prompt` parameter that biases decoding toward supplied vocabulary. So the
data and the mechanism both exist; what is missing is a path between them.

**The obstacle is the endpoint's shape.** `POST /api/transcribe` takes a file and
nothing else — it is deliberately session-less, so it has no idea which Candidate
is speaking and cannot reach their résumé.

**ADR 0015 already refused something adjacent**, and this ADR has to answer it
directly. That ADR decided *"the judge never sees the resume"* on token-budget
grounds: the capped résumé is ~4K tokens against a measured 12K TPM budget, so
piping it into every warm-up judge call would spend a third of the per-minute
budget per Turn. A reader who remembers that will expect this ADR to be refused
for the same reason. It is not the same case, and the difference is the whole
argument below.

## Decision

**Pass a short résumé-derived vocabulary digest as the Whisper `prompt`, not the
résumé itself.**

- **A digest, not the document.** Whisper's prompt window is small (~224 tokens),
  which forces the useful discipline: send proper nouns and distinctive technical
  terms — the Candidate's name, institution, project names, named
  technologies — not prose. This is why ADR 0015's token-budget objection does
  not carry over. That decision was about spending ~4K tokens of a 12K TPM LLM
  budget *per Turn*; this is a few dozen tokens against a separate STT endpoint
  with its own quota. Same instinct, different order of magnitude.
- **The digest is built once, at Session creation**, and stored alongside the
  Session — reusing ADR 0015's argument for generating warm-ups at creation
  rather than per Turn: it keeps work off the conversational critical path and
  makes the per-Turn cost zero.
- **`POST /api/transcribe` gains an optional `session_id`.** With it, the
  endpoint looks up that Session's digest and passes it to Whisper. Without it —
  no Session, no résumé, or an unknown id — transcription behaves exactly as it
  does today. **Optional, never required**: voice input must keep working before
  a Session exists and in the keyless demo (ADR 0002).
- **The client never holds the digest.** It sends a `session_id` it already has;
  the résumé-derived text stays server-side. A design where the browser stores
  and re-uploads résumé-derived PII on every Turn is strictly worse and is
  rejected.
- **No résumé, no prompt.** The curated-bank path (ADR 0015's `warm_up_source:
  "bank"`) sends no prompt at all rather than a generic one. A generic prompt
  buys nothing on proper nouns and only adds hallucination surface.

## Consequences

- **Proper nouns should improve markedly; nothing else changes.** The failure
  this targets is narrow and so is the fix.
- **It sends résumé-derived text to a new endpoint on every voice Turn.** Stated
  plainly, because ADR 0015 is explicit that résumé text is PII. Two things bound
  it: the *provider* is not new — Groq already receives the **full** résumé at
  Session creation to generate warm-ups (ADR 0015), so this crosses no trust
  boundary that is not already crossed — and what is sent is a vocabulary list,
  not the document. It is a genuine increase in *frequency* (per Turn rather than
  once per Session), and that is the honest cost.
- **Failover widens the same surface.** If Groq is unavailable the LLM path falls
  to Gemini (ADR 0014); STT has no such fallback today, so a digest reaches only
  Groq. Worth re-checking if STT ever gains a second provider.
- **Prompting increases hallucination risk in exactly the mode just fixed.** A
  Whisper prompt can bleed into the output — the model may emit prompt words that
  were never spoken, and a longer or more prose-like prompt makes this worse.
  This is why the digest is a short term list and why the "refuse to submit
  recordings that captured no speech" guard stays. **Whichever way this ADR is
  decided, that guard must not be removed.**
- **A wrong digest degrades transcription.** Biasing toward terms the Candidate
  does not say can pull ordinary words toward résumé vocabulary. The risk is
  small for distinctive proper nouns and larger for common words, which argues
  for a conservative extraction that prefers names over generic technical terms.
- **`/api/transcribe` stops being purely stateless.** A small but real coupling:
  a previously self-contained endpoint gains an optional dependency on Session
  state. Kept optional so the endpoint still works standalone.
- **The digest inherits `_resumes`' lifetime** — in-memory, dies with the process
  (ADR 0007), retention still deferred to ADR 0009. No new storage question.

## Open question: how the digest is extracted

Deliberately unresolved — it is the one part worth arguing about, and it is
cheap to change later since the digest is built in one place.

- **(a) An LLM call at Session creation.** Ask the provider to pull proper nouns
  from the résumé. Most accurate; adds a second call to a path that already makes
  one (ADR 0015) and can fail.
- **(b) Heuristic extraction.** Capitalised multi-word sequences, plus terms from
  a small known-technology list. Free, deterministic, no new failure mode;
  noisier, and will miss lowercase tooling names.
- **(c) Reuse the generated warm-up questions.** They were already generated
  *from* the résumé and name the projects and technologies. Free and needs no new
  extraction — but it systematically misses the Candidate's own name, which is
  the single worst-transcribed item in the evidence above.

**Leaning (b), with the Candidate's name taken from the résumé's opening lines**
— it adds no new failure mode to Session creation, and the evidence is that names
and institutions are what break, which heuristics catch precisely because they
are capitalised. Revisit toward (a) if heuristics prove too noisy in practice.

## Alternatives considered

- **Do nothing.** Defensible: mangled proper nouns are cosmetic in most answers,
  and the Session still functions. Rejected because the warm-up round is
  specifically *about* the Candidate's named projects (ADR 0015), so the errors
  land exactly where they cost the most.
- **Send the whole résumé as the prompt.** Rejected on the mechanism: Whisper's
  prompt window is ~224 tokens and the résumé is capped at 15,000 characters. It
  would be truncated arbitrarily, and it would revive ADR 0015's objection for
  real.
- **A résumé-aware judge instead** (ADR 0015's own named upgrade path). A
  different fix for a different problem — it would let the interviewer catch
  résumé contradictions, but would not improve transcription at all. Still open,
  still separate.
- **Post-transcription correction** — fuzzy-match transcript tokens against
  résumé vocabulary and rewrite them. Rejected: rewriting a Candidate's words
  after the fact is a worse failure mode than mis-hearing them, and a bad match
  would put words in their mouth invisibly.
- **A better STT model.** No lever here — `whisper-large-v3-turbo` is already the
  strong option on Groq's free tier (ADR 0010).

## Status

Proposed. The decision worth a second opinion is the privacy trade: résumé-derived
vocabulary leaving the server on every voice Turn rather than once per Session.
The provider is unchanged and the payload is a term list rather than the
document, which is why this is recommended — but it is a real increase in
exposure frequency, and "do nothing" remains a defensible answer for a
portfolio demo.
