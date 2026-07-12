# ADR 0005: Stack — React+Vite / FastAPI / LangGraph / Chroma

Date: 2026-07-12 · Status: accepted

## Context

Baseline framework choices for a multi-user voice web app with agentic
orchestration and RAG, built by a developer whose existing projects are
React+Vite (frontend) and Python/FastAPI (backend).

## Decision

- Frontend: React + Vite (plain JS for now; TS revisit-able later).
- Backend: FastAPI (async fits streaming voice turns).
- Agent orchestration: LangGraph (explicit state machines for the
  planner / interviewer / evaluator agents; also a target résumé keyword).
- Vector DB: Chroma, local and free, for question banks + uploaded resumes.

## Consequences

- Matches existing skills → less framework-learning overhead, faster build.
- LangGraph and Chroma are deliberate learning goals, introduced with
  primers when they first appear (tutorial-mode rule).
