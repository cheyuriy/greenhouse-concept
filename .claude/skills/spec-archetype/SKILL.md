---
name: spec-archetype
description: Design a new project archetype (taxonomy + deliverables + drafting guidance) interactively — the section tree, dependencies, the artefacts finalization must hand over, and per-section definition of "complete" for a new kind of spec. Use when the user wants to spec a kind of thing no existing archetype fits, or asks to add/modify an archetype.
argument-hint: <archetype-name>
---

# /spec-archetype — add a new kind of spec

An archetype is workspace-level, not project-level: no project resolution
needed. The name is required (kebab-case, becomes the file stem); if missing,
ask.

## 1. Check it's actually new

Read `templates/taxonomies/*.yaml`. If an existing archetype is close, say so
and offer: extend/reshape that one, start the new one from it as a base, or
proceed from scratch. Duplicating an existing tree under a new name helps
nobody.

## 2. Design the tree WITH the user

Draft a candidate section tree from what they've described (base archetype or
from scratch), then refine it through 2–3 AskUserQuestion rounds — this is a
design conversation, not a form:

- **Coverage** — which sections belong at all? Propose the tree grouped by
  workfile; let them add/drop (multiSelect works well here).
- **Depth** — where does THIS kind of thing need fine-grained sections
  (the `cli.commands`-style heart of it) vs one coarse section?
- **Dependencies** — what must be settled before what? Propose the
  `depends_on` edges and confirm the ones that aren't obvious. The edges must
  form a DAG; they drive blocker ranking and staleness, so wrong edges mean
  wrong nudges later.

## 3. Decide the deliverables WITH the user

An archetype also declares what finalization hands over **beyond SPEC.md** —
the artefacts a reader of *this kind* of spec expects to receive. A cloud
deployment wants an operator guide, a brief for Terraform generation, an
architecture scheme; a CLI wants a formal reference of every command and
flag. Never skip this: a taxonomy without deliverables produces a spec
nobody can act on without re-reading it.

One AskUserQuestion round (multiSelect): propose 3–5 candidates drafted from
the tree — each option names the artefact, its format (guide / reference
tables / mermaid diagram / IaC brief …) and the sections that would feed it
— plus Other for what you missed. Then confirm the feeding sections for
anything non-obvious. That mapping is load-bearing: `section guidance` shows
a drill which deliverables the section feeds and what each needs, so a
missing edge means the section gets drafted without the facts its artefact
requires, and a spurious one holds a deliverable hostage to an unrelated
section.

## 4. Write both files

- `templates/taxonomies/<name>.yaml` — follow the conventions of the existing
  files: kebab-case ids (dotted for hierarchy like `cli.commands`), every
  section with `workfile` + `heading`, workfiles ordered by `NN-` prefix,
  a top-of-file comment saying what this archetype is for, and a
  `deliverables:` list — per entry `id`, `title`, `format`, `path` (file name
  under `final/deliverables/`), a `description` saying what the artefact must
  contain and for whom (this is what the drill and the finalize step read),
  and `sections` (the feeding section ids; scaffold refuses unknown ones).
- `templates/docs/<name>.yaml` — guidance for EVERY section: one or two
  sentences on what a complete version covers. Not optional in practice —
  the drill loop and spec-critic use it as the definition of "complete".
  Draft it yourself; show the user only the entries you're unsure about.

## 5. Verify mechanically

```bash
uv run greenhouse new tmp-archetype-check --archetype <name>
uv run greenhouse --project tmp-archetype-check validate
uv run greenhouse --project tmp-archetype-check coverage
uv run greenhouse --project tmp-archetype-check deliverable list
rm -rf "$(uv run greenhouse --project tmp-archetype-check root --project-dir --absolute)"
```

Validate must pass (anchors resolve, deps form a DAG, deliverables name real
sections) and the coverage suggestions should look sane for a fresh project
of this kind — show the user that suggestion list and the deliverable list as
the final sanity check: "this is what the workspace will nudge you toward
first, and this is what it will hand you at the end".

## 6. Commit

`feat(templates): <name> archetype` (workspace change — no session log, those
belong to projects). Then offer `/spec-new` with the new archetype.

## Editing an existing archetype

Same flow, minus scaffolding from scratch. Template edits affect only newly
created projects; if the user wants an existing project to gain the new
sections or deliverables, that is a separate explicit step (add sections via
state tooling + drill them; `greenhouse deliverable add` per deliverable),
never a silent rewrite of their `spec-state.yaml`.
