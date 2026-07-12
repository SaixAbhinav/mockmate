# ADR 0002: LLM provider — hosted free tier primary, pluggable fallback

Date: 2026-07-12 · Status: accepted

## Context

The project must cost $0 to run, but the evaluator agent needs strong
reasoning to score answers reliably. Options ranged from fully local models
to paid APIs.

## Options

1. Paid API (OpenAI/Anthropic) — best quality, breaks the $0 constraint.
2. Hosted free tiers (Groq: 70B-class Llama at ~30 req/min free; Gemini
   Flash free tier) — near-frontier quality, rate limits fine for personal
   use + demo traffic.
3. Local via Ollama — $0 forever and offline, but consumer hardware limits
   this to small models: fine for dev, too weak for trustworthy rubric
   scoring.

## Decision

Option 2 as primary, with the provider behind a `LLMProvider` interface
(`backend/app/providers.py`) so option 3 (or a scripted no-key demo mode) is
a config change, not a code change. Provider selection order:
`GROQ_API_KEY` → `GEMINI_API_KEY` → scripted fallback.

## Consequences

- $0 maintained; quality sufficient for evaluator work.
- Rate limits cap burst traffic — acceptable; revisit only if the demo gets
  real traffic.
- The scripted fallback means the repo runs for anyone with zero setup.
