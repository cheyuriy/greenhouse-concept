---
name: spec-decide
description: Record a decision as an ADR — capture context/options/choice/consequences, link everything by id, flip the section to agreed or locked, surface newly-stale dependents. Use when the user settles a question, picks between options, or wants to lock a section down.
argument-hint: "[section-id]"
---

# /spec-decide — make it official

Resolve the project (CLAUDE.md), echo it. No section named? Infer from what's
being decided; confirm if ambiguous.

## 1. Establish what is being decided

From the conversation, state back: the question being settled, the options
that were on the table (including backlog ideas by id — `greenhouse idea list`),
and the choice the user made. If any of that is fuzzy, one AskUserQuestion to
pin it — a vague ADR is worse than none. Check `greenhouse trace <section>`
for an existing ADR this one would contradict → that's a supersede, name it.

## 2. Write the ADR

```bash
uv run greenhouse decision new --title "<the choice, as a statement>" \
  --section <s> [--section ...] \
  --idea <considered-ids...> --resolves <qids...> [--supersedes <adr>] \
  --body "<## Context / ## Options considered (with why-nots) / ## Choice / ## Consequences>"
```

Rejected options that were backlog ideas get
`uv run greenhouse idea status <id> rejected --resolution "<why, from the ADR>"`;
the accepted one (if any) `accepted --resolution <adr-id>`.

## 3. Update the prose and state

- Add/adjust the affected requirement lines through
  `uv run greenhouse section write <section> --from-file -`; attach
  `<!-- why: <adr> -->`.
- `uv run greenhouse state resolve <qid>` for each settled question.
- `uv run greenhouse state set <section> -m agreed` (or `locked` if the user
  explicitly wants it frozen — explain that changing it later requires a
  superseding ADR).

## 4. Surface the blast radius

`uv run greenhouse coverage` → if dependents of this section are now stale
(`section deps <section>` lists them), tell the user which, and offer (don't
start) a re-review drill.

## 5. Log and commit

Session log with the deliberation verbatim (`--decision <adr>` so the
`Decisions:` trailer is derived), then step 9 of `/spec-drill`: `check`,
`git -C "$(uv run greenhouse root)" add`, `session commit-message | git commit
-F -`, `session commit`, the follow-up commit.
Then, if `uv run greenhouse trello show` reports the dashboard enabled, run
the `/spec-trello` sync so the section and resolved questions move on the board.
