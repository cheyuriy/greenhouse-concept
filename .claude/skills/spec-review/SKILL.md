---
name: spec-review
description: Critique the spec — spec-critic and consistency-auditor subagents run in parallel over the project (or one section), findings come back deduped and ranked for the user to accept/reject/defer. Use when the user asks for review, critique, completeness or consistency checking.
argument-hint: "[section-id]"
---

# /spec-review — critique panel

Resolve the project (CLAUDE.md), echo it. Scope = the named section, else the
whole project.

## 1. Mechanical pass first

```bash
uv run greenhouse check --xref --json
uv run greenhouse idea audit --json; uv run greenhouse source check --json; uv run greenhouse ref check --json
```

Mechanical facts don't need a subagent's opinion — they seed the findings list
directly.

## 2. Launch both subagents in parallel (single message)

- **spec-critic** — give it the scope's workfile text, section maturities, open
  questions, guidance comments, relevant ADR summaries, and the deliverables
  each in-scope section feeds (`uv run greenhouse deliverable list --json`).
  It judges each section *against its maturity* (a stub is allowed to be
  thin; an agreed section is not), checks that agreed feeding sections carry
  the concrete facts their deliverables need, and prefers "underspecified —
  ask X" over inventing fixes.
- **consistency-auditor** — give it all workfile text, the ADR frontmatter+
  bodies, the state index, and the flagged-ideas list. It hunts cross-document
  contradictions, terminology drift, and rules on each flagged idea:
  still-relevant / absorbed / contradicted / obsolete, with evidence.

Both are read-only; they return findings, never edits.

## 3. Merge and present

Dedupe (same file+line+claim), rank: contradictions & broken invariants →
untestable/ambiguous agreed content → gaps → style. Present in batches of 2–4
via AskUserQuestion; every finding shows its evidence (`file:line`) and the
suggested fix or question. Options per finding: *Accept — fix now* /
*Accept — record as question* / *Defer* / *Reject (say why)*.

## 4. Apply what was accepted

Fix-now → edit workfiles (provenance markers intact); question →
`greenhouse state question`; idea verdicts → `greenhouse idea status` (user-
confirmed only); rejected findings worth remembering → note in the session log
so the next review doesn't resurface them identically.

## 5. Record and commit

Session log (`--slug review[-<section>]`, touched sections, questions raised,
ideas resolved), then commit: `spec(<project>): apply review findings`.
