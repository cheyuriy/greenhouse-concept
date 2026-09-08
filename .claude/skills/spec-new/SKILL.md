---
name: spec-new
description: Start a new spec project — short interview (archetype, one-liner, audience, scope), scaffold the folder contract, re-verify the deliverables the archetype promises, seed spec-state.yaml, commit. Use when the user wants to begin speccing a new product/tool/service idea.
argument-hint: <project-name>
---

# /spec-new — start a project

The project name is the one required argument; if missing, ask for it (short,
kebab-case, becomes the folder name in the workspace — `uv run greenhouse
workspace show` says where; if it reports the legacy fallback under this repo,
tell the user and offer `greenhouse workspace init <path> --use` first).

## 1. Interview (before creating anything)

One AskUserQuestion batch:

- **Archetype** — list `templates/taxonomies/*.yaml` (read the folder; each
  file's `description:`) and, per candidate, the deliverables it promises
  (`deliverables:` ids) — the archetype choice is also a choice of what the
  user gets at the end. Recommend the best fit from what the user has said.
- **One-liner** — offer 2–3 candidate one-sentence descriptions drafted from
  their words, plus Other.
- **Audience** — who is this for? Offer guesses from context.

Then one more focused exchange: *"What is clearly OUT of scope for v1?"* —
free-form; capture whatever comes back.

## 2. Scaffold

```bash
uv run greenhouse new <name> --archetype <a> --title "<t>" --one-liner "<o>" --audience "<aud>" [--audience ...]
uv run greenhouse validate --project <name>
```

Echo: `Project: <name> (created)`.

## 2b. Re-verify the deliverables

```bash
uv run greenhouse deliverable list
```

The archetype's deliverables are a default, not a decision. One
AskUserQuestion (multiSelect) listing each expected artefact with its
description — keep / drop — plus Other for artefacts this project needs that
the archetype did not foresee (a migration plan, a cost sheet, a diagram of a
specific flow). Apply the answers through the tooling only:

```bash
uv run greenhouse deliverable remove <id>
uv run greenhouse deliverable add <id> --title "<t>" --format "<f>" --description "<what it must contain, for whom>" --section <s> [--section ...]
uv run greenhouse deliverable edit <id> --add-section <s> | --drop-section <s> | --description "..."
```

If a wanted deliverable has no obvious feeding sections yet, add it with the
closest ones and record a question on the section it most depends on. The
answers go into the founding session log verbatim like everything else.

## 3. Seed the first content

- Put the one-liner + scope answers into the Overview and Scope slices via
  `uv run greenhouse section write overview --from-file -` (same for scope);
  the guidance comments are kept automatically.
- Set those sections to stub: `uv run greenhouse state set overview -m stub` (same for scope).
- Anything the user said that is *not yet decided* becomes questions:
  `uv run greenhouse state question <section> "<text>" [--blocking]`.
- Log the session verbatim (interview + deliverable re-verification):
  `uv run greenhouse session log --slug founding --touched overview --touched scope --body "<the Q&A as asked/answered>"`

## 4. Commit

Step 9 of `/spec-drill` with `--subject "found project — <one-liner>"`
(`check`, `git -C "$(uv run greenhouse root)" add`, `session commit-message |
git commit -F -`, `session commit`, follow-up commit). Finish by running
`uv run greenhouse coverage --top 3` and offering those targets as the
possible first drill (via AskUserQuestion, "stop here" included).
