---
name: spec-trace
description: Reconstruct the complete reasoning history behind any part of a spec — sessions, questions with verbatim answers, ideas considered and rejected, ADRs and supersessions — then optionally re-open it with that context. Use when the user asks why something is the way it is, what happened with X, or wants to revisit a settled part.
argument-hint: <section-id | idea-NNNN | q-… | NNNN | src-/ref-NNNN | REQ-…>
---

# /spec-trace — the story of an id

Resolve the project (CLAUDE.md), echo it. The target can be a section id,
idea, question, ADR number, source/reference id, or REQ id — if the user gave
a fuzzy phrase instead ("the auth thing"), match it to an id via
`greenhouse state show` / `idea list` and confirm.

## 1. Reconstruct

```bash
uv run greenhouse trace <id> --context
```

## 2. Narrate

Retell it as a short story, not a log dump: where it started, what was asked
and answered (quote the user's own words for pivotal answers), which options
lived and died and why, what superseded what, where it stands now. Cite ids
inline so everything is followable. Flag anything the trace exposes as odd —
a decision no prose cites, a reversal without an ADR, a question that quietly
disappeared.

## 3. Offer re-evaluation

One AskUserQuestion: *Re-open as a drill (with this context loaded)* /
*Just wanted the story* / *Something in the record is wrong*. Re-open →
`/spec-drill <section>` skipping its LOAD step (already done). Record-is-wrong
→ fix through tooling (a superseding ADR, an idea status change) — never by
editing history files.

Read-only otherwise: tracing alone changes nothing and commits nothing.
