---
name: spec-drill
description: The core iterative loop — deepen one spec section through questions-first drafting, ending with the user's sign-off, full history capture, and a commit. Use whenever the user wants to work on, detail, flesh out, or revisit a specific part of a spec.
argument-hint: "[section-id]"
---

# /spec-drill — the core loop

Resolve the project (CLAUDE.md), echo it. No section given? Run
`uv run greenhouse coverage` and offer the top targets. Keep a running
note of ideas/questions that surface mid-drill — step 8 sweeps them.

## 1. LOAD

```bash
uv run greenhouse section guidance <section>   # the local definition of "complete" + the deliverables this section feeds
uv run greenhouse section deps <section>       # upstream chain + what this unblocks
uv run greenhouse section show <section>       # current slice (may be a placeholder)
uv run greenhouse state show <section>         # questions, assumptions, back-links
```

`section guidance` ends with **"Feeds deliverables"** when the section is an
input to one of the artefacts finalization hands over (operator guide,
Terraform brief, command reference …). Read each deliverable's description as
a list of facts this section must carry in concrete form — the actual
commands, resource names, ports, role names — because the finalize step will
write that artefact from this prose alone. It is a floor, not the agenda: the
guidance comment still defines complete, and a section is never trimmed to
what its deliverables happen to need.

If the section's maturity > `none`:
`uv run greenhouse trace <section> --context` — prior Q&A verbatim, rejected
ideas with reasons, ADRs, transitions. Also load the upstream sections'
current text (`section show` on each `depends_on`) and open backlog ideas
whose `relates_to` includes it. **Never re-ask what the trace already answers.**

## 2. FRAME

Write the current framing as 3–5 numbered statements (from trace + workfile +
the user's fresh words). Put those statements **verbatim inside the
AskUserQuestion `question` text** — the user can only agree to text they can
see in the prompt itself; framing printed as ordinary output before the call
doesn't count. Options: confirm all / correct (they name the statement number
and the fix via Other or the notes field). A correction of something
previously *agreed* is a decision reversal — say so, and route the change
through an ADR at step 7.

## 3. PROBE

2–4 AskUserQuestion batches, most-consequential first (what gates dependents,
what the guidance says is missing, what the critic/backlog flagged, then what
the fed deliverables would still lack — ask for the concrete value, not
whether it matters). Every option: a recommendation first, honest trade-offs
on each. "I don't know yet"
is always a valid outcome → record it:
`uv run greenhouse state question <section> "<text>" [--blocking]` (blocking iff
dependents can't proceed without it). **Do not draft while probing.**

## 4. DRAFT

Only now write/update the section's slice. Get the ADR id the RECORD step
will assign (`ADR=$(uv run greenhouse decision next-id)`) and cite it in the
draft's markers. Write the slice through the tool, heading included:

```bash
uv run greenhouse section write <section> --from-file - <<'EOF'
## <the section's heading, unchanged>

…prose…
EOF
uv run greenhouse check --pending-adr $ADR
```

`section write` replaces exactly the slice between the heading and the next
heading of the same or higher level, keeps the guidance comment, and refuses
a wrong heading — never patch workfiles with ad-hoc regex. Requirements as
`**REQ-<SECTION>-<NNN>** … Acceptance: …`, provenance markers on decided
things (`<!-- why: $ADR -->`), ref markers on source-derived facts
(`<!-- ref: … -->` — and run `greenhouse ref lookup` before fetching anything
external). Unavoidable assumptions: `> **ASSUMPTION:** … (basis: …)` +
`greenhouse state assume`. Amending an *agreed* neighbour section (with the
user's confirmation) is the same `section write` on that section, followed by
`state set <neighbour> -m agreed` in RECORD to re-affirm it.

## 5. SHOW

Present the drafted section (or diff if revising) and an explicit
**"What I did NOT decide"** list: open questions, assumptions, deliberate
blanks — and, when the section feeds deliverables, what each of those
artefacts would still be missing from this section as drafted.

## 6. SETTLE

One AskUserQuestion with exactly these three options, each carrying its
description so the user sees what the choice does to the section:

- **Agree as-is** → maturity `agreed`. Description: "This is decided. The
  section is recorded as signed off (`agreed_at` stamped), drops out of the
  coverage queue, and later changes to what it depends on will flag it as
  stale for re-review. Not available while a blocking question is open."
- **Good enough as draft** → maturity `draft`. Description: "Keep the text,
  but it is not decided. Open questions stay open and coverage keeps listing
  the section as work remaining. Pick this when the prose is useful or when
  blocking questions still prevent `agreed`."
- **Revise** → back to PROBE with their notes. Description: "Not yet. Nothing
  is recorded; add notes and the drill asks further questions or reworks the
  draft, then returns here."

Put *Agree as-is* first only when no blocking question remains; otherwise
lead with *Good enough as draft*. Never mark `agreed` yourself without this
explicit confirmation; the tool refuses `agreed` while blocking questions
remain — that refusal is correct, don't force it.

## 7. RECORD

```bash
uv run greenhouse state resolve <qid>          # each question answered
uv run greenhouse decision new --title "..." --section <s> --resolves <qid> --idea <id> --body-file - <<'EOF'   # if a real decision was made
<context / options considered / choice / consequences>
EOF
uv run greenhouse state set <section> [<re-affirmed neighbours…>] -m <maturity>
uv run greenhouse session log --slug <topic> --touched <s> --transition <s>:<from>:<to> --asked <qids> --resolved <qids> --decision <adr> --body-file - <<'EOF'
<Q&A verbatim>
EOF
```

The ADR must receive the id from DRAFT (`decision new` assigns the next free
id; if `next-id` now prints something else, another ADR landed in between —
fix the markers). The session body carries the questions as asked and the
user's answers **verbatim**.

## 8. SWEEP

Ideas raised but not pursued → `uv run greenhouse idea add "<title>" --relates <s> --source drill --body "<context>"`
(if it refuses as a near-duplicate, cite the existing id in the session log
instead). Backlog ideas this drill absorbed/killed →
`uv run greenhouse idea status <id> accepted --resolution <adr>` or
`rejected --resolution "<why>"`.

## 9. COMMIT

Git stays visible here on purpose (CLAUDE.md git protocol); the CLI only
supplies the root, the message, and the sha.

```bash
ROOT="$(uv run greenhouse root)"; DIR="$(uv run greenhouse root --project-dir)"; SID=<session-id>
uv run greenhouse check                                   # fix errors first
git -C "$ROOT" add "$DIR"
uv run greenhouse session commit-message "$SID" --subject "<what was settled>" \
  | git -C "$ROOT" commit -q -F -
uv run greenhouse session commit "$SID"                   # records HEAD's sha, prints the follow-up subject
git -C "$ROOT" add "$DIR"
git -C "$ROOT" commit -q -m "spec(<project>): attach commit hash to session $SID"
git -C "$ROOT" status --short                             # must print nothing
```

Add any session-attribution trailer the harness asks for via
`--trailer "Key: value"` on `commit-message` (and on the follow-up `-m`).
**Never amend** the spec commit: amending would change the sha just recorded.

## 10. OFFER

If `uv run greenhouse trello show` reports the dashboard **enabled**, run the
`/spec-trello` sync now (before the menu): it pushes the new maturity and
question state to the board and writes nothing to the tree.

`uv run greenhouse coverage` — one AskUserQuestion: adjacent/newly-exposed next
targets, or stop. Stopping is a first-class option; never chain drills
uninvited.

## Stopping early

If the drill ends before step 9 for any reason (the user stops, changes topic,
runs out of time), do **not** leave the project dirty — the next session may
resolve to a different project, and leftover changes would tangle two projects
into one commit. Log the session (`greenhouse session log` with whatever
actually happened, answers verbatim), then run step 9 with
`--subject "wip — <section> drill paused (<where it stopped>)"`. A committed
WIP beats a clean-looking history with a dirty tree.
