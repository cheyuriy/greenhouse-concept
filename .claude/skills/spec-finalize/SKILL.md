---
name: spec-finalize
description: Promote agreed/locked sections to final/ shards, build the single-file SPEC.md, and write the project's deliverables (operator guide, IaC brief, references, diagrams) under final/deliverables/ — gated by validate/lint/xref, source references stripped, leak check fail-closed. Use when the user wants the deliverable spec produced or refreshed.
argument-hint: "[project]"
---

# /spec-finalize — produce the deliverable

Resolve the project (CLAUDE.md), echo it.

## 1. Gate

```bash
uv run greenhouse check --xref
uv run greenhouse coverage          # includes deliverable readiness
```

- Validation/lint **errors**: fix them first (through tooling), don't finalize
  over them.
- Lint **warnings** on promotable sections (missing acceptance criteria,
  source-only justification): present them — each is either fixed now or
  consciously waived by the user.
- **Blocking questions open**: report which, and stop. Only if the user
  explicitly says to proceed anyway use `--allow-blocking`, and say in the
  output that the spec ships with named open blockers.

## 2. Preview

From coverage, tell the user exactly what will ship: which sections
(agreed/locked) and — just as important — which will NOT (draft/stub/none), so
the promotion is a conscious cut, not a surprise. Same for the deliverables:
which are *ready* (every feeding section agreed/locked), which are waiting
and on what, which existing files are *stale*. One AskUserQuestion:
proceed / drill a missing section first / stop.

## 3. Bundle

```bash
uv run greenhouse bundle [--allow-blocking]
```

A **LeakError is never overridden**: find the offending content, restate the
fact on its own terms (public URLs may go in a `## References` section), rerun.
Never hand-edit `final/` to get past it.

## 3b. Write the deliverables

```bash
uv run greenhouse deliverable plan          # per deliverable: needs, readiness, inputs (shards/slices)
```

For every deliverable that is **ready** or **stale**, draft the artefact
yourself from its inputs — the promoted shards under `final/` are the source
of truth (workfile slices only for `--allow-unready` runs) — in the declared
format, following the description as the contents checklist. An operator
guide is written for the person on call; a Terraform brief lists resources,
variables and per-environment values; a diagram deliverable carries the
mermaid block plus legend and narrative; a reference deliverable is tables,
not prose. Restate facts on their own terms: nothing under `final/` may cite
`sources/` or `history/references/`. Then land each one through the tool:

```bash
uv run greenhouse deliverable write <id> --from-file - <<'EOF'
…the artefact…
EOF
```

`deliverable write` strips markers, leak-checks fail-closed, stamps
`built_at` and regenerates `final/deliverables/README.md`. Deliverables that
are **not ready** are reported with the sections they wait on and skipped —
`--allow-unready` only when the user explicitly says so, and the report must
then say the artefact was written from unagreed prose. Never hand-write a
file under `final/deliverables/`.

## 4. Verify and report

Skim `final/SPEC.md`: TOC present, no markers, no internal paths, reads as a
standalone document. Open each written deliverable and check it against its
description — an operator could follow the guide, an engineer could generate
the IaC, the diagram renders. Report shard list, deliverables written / left
unwritten (with why), and what was deliberately left out.

## 5. Log and commit

Session log (`--slug finalize`), then step 9 of `/spec-drill` with
`--subject "finalize — <scope>"` (`final/` is under the project dir, so the
same `git add` covers it).
