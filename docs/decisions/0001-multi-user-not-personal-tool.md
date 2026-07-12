# ADR 0001: Multi-user product, not a personal tool

Date: 2026-07-12 · Status: accepted

## Context

The app began as a personal interview-prep tool. Its personalization ideas
(reading the owner's study vault and spaced-repetition history) only work for
one specific user, but the deployed app is also a portfolio demo that
strangers must be able to try.

## Options

1. Personal tool — hardcode the owner's vault and history.
2. Multi-user — personalization behind an interface; any user uploads a
   resume and picks domains; the owner's vault is one adapter on that
   interface (local mode only).

## Decision

Option 2. Anyone can use the deployed app; owner-specific data sources plug
into a `PersonalizationSource` interface rather than being wired into core.

## Consequences

- Public demo works for any visitor (upload resume → get interviewed).
- Slightly more upfront design (an interface where a direct call would do).
- Session/user state needs a real storage story earlier than a personal tool
  would have needed it.
