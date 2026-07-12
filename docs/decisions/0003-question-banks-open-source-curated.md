# ADR 0003: Question banks — open-source seeds + curated expansion

Date: 2026-07-12 · Status: accepted

## Context

Each interview domain (ML/GenAI, CS fundamentals, HR/behavioral, later DSA)
needs a question bank with follow-ups and scoring rubrics. Paid platforms'
banks are off-limits; pure LLM generation risks shallow or wrong questions.

## Options

1. Scrape interview-prep sites — licensing and quality problems.
2. LLM-generate everything — cheap but unvetted.
3. Seed from permissively-licensed open collections (e.g. the
   awesome-interview-questions aggregator, Chip Huyen's ML interview
   questions, standard STAR/behavioral lists), normalize into our own YAML
   schema (domain / topic / difficulty / follow-ups / rubric), then expand
   with LLM assistance under human review.

## Decision

Option 3. Licenses verified per source at ingestion time. The YAML schema is
ours, so retrieval and rubric design don't depend on any source's format.

## Consequences

- Ingestion/normalization work up front, clean retrieval later.
- Human review of expanded questions is a standing chore (doubles as the
  owner's own interview prep).
