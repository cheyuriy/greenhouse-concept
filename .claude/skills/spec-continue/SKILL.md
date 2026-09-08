---
name: spec-continue
description: Resume spec work — resolve the project from CWD, compute coverage (blanks, blockers, stale sections, flagged ideas), recall recent sessions, and offer a ranked menu of what to work on. Use at the start of any returning session, or when the user asks "where were we" / "what's next".
argument-hint: "[project]"
---

# /spec-continue — session opener

## 1. Resolve and orient

Resolve the project per CLAUDE.md: `uv run greenhouse workspace show` (exit 2
= ambiguous → AskUserQuestion over `uv run greenhouse projects`, then `-p
<name>` on every call). Echo `Project: <name> (workspace <path>, resolved by
<how>)`. Then gather, in parallel where possible:

```bash
uv run greenhouse coverage            # histogram, stale, blockers, top targets
uv run greenhouse idea audit
uv run greenhouse session list -n 3   # then `session show <id>` for the verbatim outcomes
uv run greenhouse state questions
uv run greenhouse trello show      # exit 3 = no dashboard; enabled → mention the board URL
```

Do NOT re-read all workfiles — the state index is the map; `section show
<id>` reads one slice when a suggestion needs context.

Also check `git -C "$(uv run greenhouse root)" status --short`. A previous
session should never have left uncommitted changes; if it did, settle them
**before any new work**, in per-project commits: changes under another
project get their own `spec(<other-project>): …` commit (typically
frontmatter sha-attachment residue → `spec(<p>): attach commit hash to
session <id>`), never mixed into this project's commits.

## 2. Brief the user

A compact picture, not a dump: maturity histogram in one line, then the 3–5
highest-scored suggestions from coverage with *why each matters now*
(what a blank unblocks, what made an agreed section stale, which blocking
question gates the most, which deliverable a fill brings closer to ready).
Mention flagged ideas if any, and deliverables that are ready to write or
stale (their file predates a change to a feeding section).

## 3. Offer the menu

One AskUserQuestion, options built from the top suggestions, each labeled by
action (`Fill: auth`, `Re-review stale: cli.commands`, `Answer blocker:
q-config-1`, `Triage N ideas`, `Rebuild deliverable: operator-guide`), with
the reason as description. Recommended
option first = highest score. The user can always pick their own topic via
Other.

## 4. Hand off

- Section work → follow the `/spec-drill` skill for the chosen section.
- Idea triage → follow `/spec-idea` (no topic).
- A blocking question → drill the owning section, starting at that question.
- A stale or ready deliverable → `/spec-finalize` (its deliverable step
  rewrites the file from the promoted shards).
