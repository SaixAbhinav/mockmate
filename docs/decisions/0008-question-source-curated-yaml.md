# ADR 0008: Question source for v1 — curated YAML, LLM only for follow-ups

Date: 2026-07-14 · Status: accepted

## Context

The interviewer agent (ADR 0006) needs a question source for its first
domain (ML/GenAI). Full LLM generation is unvetted; RAG (Chroma) is Day 3+
scope.

## Decision

~15 seed questions in `backend/app/questions/ml_genai.yaml`, using the
schema from ADR 0003 (domain/topic/difficulty/question/follow_up_hints).
Probe and Clarify follow-ups (ADR 0006) are LLM-generated, grounded by each
question's `follow_up_hints`.

## Consequences

- Keeps Day 2 scope sane; the ADR 0003 schema means retrieval/RAG slots in
  later (Day 3+) without reworking the question format.
