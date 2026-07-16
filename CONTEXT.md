# MockMate

A voice-based AI mock interviewer. It serves two audiences at once, with no priority order set between them yet: the owner's personal interview prep, and a public multi-user demo strangers can try.

## Language

**Candidate**:
The person being interviewed in a session — either the owner or a public visitor. The intended model (ADR 0009, a future day) is that every Candidate gets a real account (email/OAuth), since interview history and personalization are meant to persist for everyone, not just the owner. Until that day, Candidates are anonymous and Sessions are not yet account-scoped.
_Avoid_: User, visitor

**Owner**:
Abhinav specifically. A Candidate whose personalization sources (study vault, spaced-repetition history) are a local-only adapter (ADR 0001) — not a distinct technical role from other Candidates.
_Avoid_: Admin

**Domain**:
A subject area an interview covers, each with its own question bank — ML/GenAI (the only one for v1), later CS fundamentals, HR/behavioral, DSA (ADR 0003). A Candidate picks one Domain per Session.
_Avoid_: Topic (reserved for the finer-grained field within a question, per the YAML schema), category, subject

**Session**:
One complete interview, from Domain pick through wrap-up. Owns the question queue, current phase, and the single shared probe+clarify follow-up counter. Identified anonymously for now; becomes Candidate-scoped once accounts exist (ADR 0009).
_Avoid_: Interview (the product concept), conversation

**Question queue**:
The fixed, ordered list of questions a Session will work through, built by `plan_session`: a random draw of N (~6–8) from the domain's bank, sorted easy→hard by difficulty. Fixed length gives the "question 3 of 8" progress UI a real denominator. RNG is seeded so tests stay deterministic.
_Avoid_: Question plan, question list

**Turn**:
One question/answer exchange within a Session. `/api/turn` (walking skeleton) handled a single Turn with no Session context; Day 2's `/api/session/{id}/answer` handles a Turn inside a real Session.
_Avoid_: Message, exchange

**Transcription**:
Turning a candidate's spoken answer into the text the interviewer judges. Primary path is server-side Groq Whisper via `POST /api/transcribe` (audio → text, shown to the candidate before sending); the browser Web Speech API is the no-key fallback. Distinct from the answer itself — the answer endpoint always receives text, never audio (ADR 0010).
_Avoid_: STT (fine in prose, but "Transcription" is the domain step), speech recognition

**Probe**:
A follow-up question on the *same* question's topic, asked when the candidate's answer was on-topic but shallow/incomplete. Shares the follow-up budget with Clarify (2 total per question).
_Avoid_: Follow-up (ambiguous with question bank's `follow_up_hints`, which are input to a Probe, not the Probe itself)

**Clarify**:
A follow-up asked when the candidate's answer was off-topic or showed they misunderstood the question — distinct from Probe (which responds to a shallow-but-on-topic answer). Shares the same 2-per-question follow-up budget as Probe; when the budget runs out and the candidate is still unresolved, the question is marked `answered: false` in Session state before advancing, so a future evaluator agent can tell abandoned questions apart from shallow-but-answered ones.
_Avoid_: Probe (different trigger condition)

**Wrap-up**:
The Session's ending: a brief LLM-generated closing remark (no scoring — that is the Evaluation's job), after which phase is `done`. Graph-triggered when the question queue is exhausted, *not* something the interviewer LLM chooses — session length is deterministic. The closing text comes from a separate structured call in "wrap-up mode".
_Avoid_: Summary, feedback, results (all imply scoring, which wrap-up deliberately does not do — see Evaluation)

**Evaluation**:
The scored assessment of a completed Session: a Score per question, the Dimension averages, Coverage, and a prose assessment with strengths and improvements. Produced by the evaluator agent after Wrap-up — never by Wrap-up itself (ADR 0011). Read on screen, never spoken; the Wrap-up is the last thing a Candidate hears.
_Avoid_: Report, results, feedback, grade

**Score**:
One question's rating within an Evaluation: its three Dimensions plus a one-sentence comment. A question the Candidate never really answered gets no Score.
_Avoid_: Rating, mark

**Dimension**:
One axis of a Score — correctness, depth, or clarity — each an integer 1–5. The rubric is generic across questions, not authored per question (ADR 0011).
_Avoid_: Metric, criterion

**Coverage**:
How many of a Session's questions the Candidate actually answered, out of the total. Distinct from the Dimension averages, which are means over answered questions only.
_Avoid_: Completion, attempt rate

**Stage**:
One of the phased Session's rounds — intro, warm_up, or dsa (Day 5) — carried as a tag on every question-queue entry and completed record (ADR 0012/0015). Distinct from the turn-level `phase` (asking/probing/clarifying/advancing/done), which describes what is happening within the current question.
_Avoid_: Phase (taken by the turn-level state), round, section

**Intro**:
The fixed opening question ("tell me about yourself"). Scripted and never LLM-paraphrased; judged for Probe/Clarify like any question but excluded from the Evaluation (ADR 0015).
_Avoid_: Icebreaker, warm-up (a different Stage)

**Warm-up**:
The Stage after the Intro: 2–3 questions about the Candidate's own background — resume-grounded when a Resume was uploaded and a provider is available, otherwise a curated draw of 3 from the Domain's bank. Note: unrelated to Wrap-up, despite the sound.
_Avoid_: Screening, background round

**Resume**:
The Candidate's uploaded CV (PDF or plain text), reduced at upload to capped plain text that grounds Warm-up generation. Held in memory only, anonymous, dies with the process (ADR 0007/0009/0015). It is PII: never logged, never echoed into errors.
_Avoid_: CV (in code and API names; fine in prose)
