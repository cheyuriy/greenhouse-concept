---
name: spec-idea
description: Generate fresh alternatives for a topic via the idea-scout subagent (deduped against the backlog), or with no topic, triage the open idea backlog. Use when the user wants options, brainstorming, prior art, or to review accumulated ideas.
argument-hint: "[topic]"
---

# /spec-idea — scout or triage

Resolve the project (CLAUDE.md), echo it.

## With a topic: scout

1. Load the backlog: `uv run greenhouse idea list --json` — ALL statuses.
2. Launch the `idea-scout` subagent. Its prompt must include: the topic; the
   project one-liner + audience; the relevant sections' current text; and the
   **exclusion list** — every existing idea's id, title, fingerprint, and (for
   rejected ones) the rejection reason — with the instruction to return
   near-matches only as `variant_of: <id>` with the delta stated, never as
   fresh duplicates.
3. Present its 3–5 options in one AskUserQuestion (multiSelect): label = the
   idea, description = trade-offs + precedent; variants labeled
   "variant of idea-NNNN". User picks which to keep / pursue now / discard.
4. Record every returned idea regardless of the user's verdict:
   `uv run greenhouse idea add "<title>" --relates <sections> --source idea-scout --body "<pros/cons/precedent>"`;
   immediately `idea status <id> rejected --resolution "<user's reason>"` for
   discards. Pursue-now picks hand off to `/spec-drill` on the section.
5. If the scout returned web extractions, cache them:
   `uv run greenhouse ref add <url> --title "..." --body "<extraction + Not extracted list>"`.
6. Commit (`spec(<project>): scout ideas on <topic>`, `Ideas:` trailer).

## Without a topic: triage

1. `uv run greenhouse idea list --status open --json` + `idea audit --json`.
   Nothing open → say so, suggest `/spec-continue`.
2. Walk the open ideas (audit-flagged first, oldest next), batching 2–4 per
   AskUserQuestion. Each idea: title + age + flags as description; options
   *Pursue now* / *Keep open* / *Defer* / *Reject*.
3. Apply: pursue → `/spec-drill` on its section afterwards; keep →
   `greenhouse idea status <id> open` is a no-op, just note it was reviewed
   (`last_checked` refreshes via audit tooling); defer/reject →
   `idea status ... --resolution "<why>"`. Never silently drop one.
4. Log a short session (`--slug idea-triage`, ideas resolved listed) and commit.
