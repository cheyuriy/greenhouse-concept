# Greenhouse Concept — operating rules

This repo grows raw ideas into specifications through iterative, interactive
sessions. These are the standing rules for every session; the `/spec-*` skills
implement the workflows, but the rules apply even outside them.

## Scope: which workspace, which project?

Projects live in a **workspace**, normally a separate git repo marked by a
`greenhouse.toml`, never in this tooling repo (its `projects/` is only the
git-ignored zero-config fallback). Resolve the workspace once per task
(`greenhouse.workspace.find_workspace`, used by every CLI command): the
`GREENHOUSE_WORKSPACE` env var → `workspace =` in the git-ignored
`greenhouse.local.toml` of this checkout (`greenhouse workspace use <path>`)
→ nearest `greenhouse.toml` above the CWD → nearest `.git` (legacy).

Then resolve the project, by this rule (`greenhouse.state.resolve_project`):

1. An explicit project name in the command/request always wins (`-p <name>`).
2. Otherwise walk up from the current working directory to the nearest folder
   containing `spec-state.yaml` — only when the CWD is inside the workspace
   (sessions usually run from this repo, so this rarely fires).
3. Otherwise the default project of this checkout, if one was set with
   `greenhouse workspace project <name>` (never written by the AI on its own).
4. Otherwise, if the workspace has exactly one project, use it silently.
5. Several projects and no signal → **ask** (AskUserQuestion listing them from
   `greenhouse projects`: coverage summary + last-touched; the user may also
   type a name). Never pick. Then pass `-p <name>` on every CLI call of the
   session — the CLI exits 2 on ambiguity, so a forgotten flag fails loudly.
6. None → suggest `/spec-new`.

`greenhouse workspace show` prints all of this. State the result in your
first line of output:
`Project: bq-assist (workspace ~/specs, resolved by default)`. Derive every
write path from the resolved project root — never from a relative path — so a
session can never leak edits into a sibling project or into this repo.

## Spec state model

- Maturity ladder: `none` (expected by taxonomy, nothing written) → `stub`
  (topic named, questions open) → `draft` (prose exists, questions remain) →
  `agreed` (the USER explicitly confirmed; no blocking questions — the tool
  refuses otherwise, and that refusal is correct) → `locked` (frozen; changing
  it requires a superseding ADR). Only the user's sign-off bumps to
  agreed/locked; downgrades are allowed and clear `agreed_at`.
- A question is `blocking` iff dependent sections cannot responsibly proceed
  without its answer — that flag drives the blocker ranking, so don't inflate it.
- `greenhouse coverage` derives the work queue: blanks, blockers ranked by
  transitive downstream impact, and staleness — an agreed section whose
  `depends_on` sections changed after its `agreed_at`, or whose cited source
  drifted on disk. Treat stale re-reviews as the top of the menu; staleness is
  the mechanism that keeps random-order work consistent.
- `depends_on` edges are load-bearing (blockers, staleness) — set them
  deliberately when adding sections, not decoratively.
- **Deliverables** are the artefacts finalization hands over beyond
  `SPEC.md` (operator guide, Terraform brief, command reference, diagram…).
  The archetype declares them, `/spec-new` re-verifies them per project, and
  each names the sections that feed it. `section guidance` shows a drill
  which deliverables the section feeds and what each needs: carry those facts
  in concrete form (a floor), never trim the section to them (not a ceiling).
  A deliverable is *ready* when every feeding section is agreed/locked and
  *stale* when a feeding section moved after its file was built; coverage
  reports both. Mutate only via `greenhouse deliverable add|edit|remove`;
  write files only via `greenhouse deliverable write` (leak-checked).

## Interaction: ask, don't invent

- Ask before writing. A gap in the user's intent is never filled with an
  invention — record it: `greenhouse state question <section> "<text>" [--blocking]`.
- Batch 2–4 questions per AskUserQuestion call; put a recommended option first
  with its rationale and honest trade-offs on every option.
- Mark unavoidable assumptions inline (`> **ASSUMPTION:** … (basis: …)`) and
  mirror them: `greenhouse state assume <section> "<text>"`.
- End every drill with the diff and a **"what I did NOT decide"** list.
- Do not re-litigate settled questions: before re-opening any section that is
  not `none`, load `greenhouse trace <section> --context` first.

## Writing conventions

- Requirement ids: `**REQ-<SECTION>-<NNN>**`, globally unique, each with an
  `Acceptance:` criterion or an explicit `[needs-criterion]`. Lint enforces.
- RFC 2119 keywords (MUST/SHOULD/MAY) used deliberately; bare "should" in
  spec prose gets flagged.
- An idea is never dropped and never invented twice: raise it →
  `greenhouse idea add`; reuse it → cite its id; reject it →
  `greenhouse idea status <id> rejected --resolution "<why>"`.
- `final/` is machine-generated (`greenhouse bundle` for shards and SPEC.md,
  `greenhouse deliverable write` for `final/deliverables/`). Never hand-edit it.

## Traceability (ids are the memory)

- Mutate state only through `greenhouse` commands — never hand-edit
  `spec-state.yaml`, `IDEAS.md`'s indexed parts, or `history/INDEX.md`.
- Never write a history file by hand: `greenhouse session log` and
  `greenhouse decision new` produce complete frontmatter links and back-links.
- Session logs record the questions **and the user's answers verbatim** — the
  reasoning, not a paraphrase.
- New requirements and ADR-derived statements carry `<!-- why: <adr>, <idea> -->`
  provenance markers.
- Ids are permanent. Rename a section only by adding the old id to `aliases`.
- `history/` and git are complementary, not redundant: git records *what bytes
  changed*; `history/` records *what was decided and why*, in a form to re-read
  (`greenhouse trace`) instead of re-litigating settled questions.

## Templates: adding a new archetype

`templates/` is the extension point for new *kinds* of specs. When a user
wants to spec something none of the existing archetypes fits (check
`templates/taxonomies/*.yaml` first — reshaping an existing tree during
`/spec-new` is often enough), offer `/spec-archetype` — it designs the
section tree WITH them (a few AskUserQuestion rounds), not for them.
The rules below apply to any archetype work, skill-driven or not:

- An archetype = `templates/taxonomies/<name>.yaml` (required: sections +
  `deliverables:`) + matching `templates/docs/<name>.yaml` guidance (write it
  — the drill loop and spec-critic depend on it as the definition of
  "complete").
- Every archetype declares its `deliverables:` — what a reader of this kind
  of spec expects to receive at finalization — and `/spec-archetype` asks the
  user which ones (multiSelect) rather than guessing; each names its feeding
  `sections` (scaffold refuses unknown ids) and a `description` that is the
  artefact's contents checklist.
- Taxonomy conventions: kebab-case section ids, dotted for hierarchy
  (`cli.commands`); every section names its `workfile` and `heading`;
  `depends_on` must form a DAG over foundations (overview → scope →
  requirements → detail sections); workfiles ordered by `NN-` prefix.
- Verify before offering it: scaffold a throwaway project in a temp dir with
  `create_project()` and run `validate` on it (see
  `test_projects_scaffold_under_projects_dir` / the archetype check in tests),
  or `uv run greenhouse new tmp-check --archetype <name>` + `validate` +
  `deliverable list` + delete the folder.
- Template edits affect only newly created projects; never rewrite an existing
  project's `spec-state.yaml` to match a changed template — that is a drill.
- Commit as `feat(templates): <archetype>`.

## Sources and references

- Two marker syntaxes, never mixed, with different fates at promotion:
  `<!-- why: 0003, idea-0007 -->` = internal provenance (ADRs, ideas) — lives
  in workfiles and the trace graph, stripped from `final/` shards;
  `<!-- ref: src-0003, ref-0011 -->` = external material (sources, cached
  references) — stripped AND leak-checked: those ids must not survive
  anywhere under `final/`.
- `sources/` holds original curated material (replaced only by the user,
  checksum-tracked); `history/references/` holds AI-written extractions of
  ad-hoc links/files (volatile ones expire; `greenhouse ref promote` graduates
  one into `sources/` when it turns out foundational).
- **Before fetching any URL or reading any out-of-project file, run
  `greenhouse ref lookup <url|path>`** (exit 0 = fresh hit, use it and skip the
  fetch; 3 = stale, refetch and re-add; 4 = miss, fetch then `greenhouse ref add`
  with the extraction *and a "Not extracted" list*). This applies to subagents too.
- Curated material the project is built on → `/spec-source` / `greenhouse source add`.
- Nothing under `final/` may reference `sources/` or `history/references/`.
  Facts are restated on their own terms; a public URL may appear in a
  `## References` section, an internal document never. The bundle leak check
  is fail-closed and never overridable.
- Never quote a `confidential: true` source at length — extract the fact.

## Trello dashboard (optional, read-only mirror)

- A project opts in through `greenhouse trello configure --board "<exact
  board name>" --enable`; that writes the `trello:` block of `spec-state.yaml`
  (the only way to edit it). No block, or `enabled: false` → Trello is never
  touched for that project.
- Direction is one-way: spec state → board. `/spec-trello` pushes
  `greenhouse trello plan --json` (lists in order, one card per section,
  open/answered question, idea, plus a status card) through the `trello` MCP
  server. Nothing on the board is ever read back into state, ideas, or
  history; a change someone makes on a card is overwritten by the next sync.
- Card identity is the `[<id>]` prefix of the card name. Cards without that
  marker, and lists the plan does not name, belong to the user — never
  edit, move, or archive them.
- When `trello show` reports enabled, run the `/spec-trello` sync after every
  spec commit (drill, decide, finalize, review-apply). A sync writes nothing to
  the tree, so it needs no commit; the exception is recording the board URL
  after the first sync (`trello configure --url`), which is committed on its
  own.

## Git protocol

Commit when a significant step completes — you decide when, by this definition:

- **Commit after:** a section's maturity changed; a batch of questions was
  answered; an ADR was written; review findings were applied; a finalize run;
  tooling/template changes.
- **Do not commit:** mid-drill while work continues, drafts you are about to
  keep editing, pure reads.
- **Never end a session with a dirty tree.** If work stops mid-drill, commit
  the partial state as `spec(<project>): wip — <what's in flight>` (with a
  session log) before stopping — the next session may resolve to a different
  project, and leftover changes would tangle two projects into one commit.
- **Sync the workspace repo before touching state.** The workspace normally
  lives in its own repo, often edited from more than one machine. When that
  repo has a remote (`git -C "$(uv run greenhouse root)" remote` prints
  one), the first thing a session does after resolving the project — before
  `coverage`, `trace`, or any write — is `git -C "$(uv run greenhouse root)"
  pull --ff-only`, so the session starts from the latest state instead of
  producing a conflicting commit. Settle a leftover dirty tree first (see
  above), never stash around it. A refused fast-forward (diverged branch, no
  upstream) is stopped on and shown to the user, never merged or rebased
  silently. The complement: after the session's last spec commit, `git -C
  "$(uv run greenhouse root)" push` when a remote exists, so the next machine
  finds this work. No remote (the legacy fallback under this checkout, or a
  purely local workspace) → nothing to sync; say so once and continue.
- **Git never runs inside `greenhouse`.** Every `git add`/`git commit` is a
  visible line in a skill; the CLI only prints what the commit needs. Run every
  git call as `git -C "$(uv run greenhouse root)"`: `root` prints the git root
  of the *resolved project* (the workspace repo, not this checkout), so the
  working directory can never turn a pathspec into a failure or land a spec
  commit in the tooling repo. Spec commits and tooling commits therefore go to
  different repos; a session touching both makes two commits.
- Spec commits: `spec(<project>): <what was settled>` with machine-readable
  trailers (no attribution trailers):

  ```
  Sections: auth, config
  Ideas: idea-0007
  Decisions: 0003
  Session: 2026-08-26-auth-model
  ```

  `greenhouse session commit-message <session-id> --subject "<what was
  settled>"` prints exactly this from the session's frontmatter — pipe it into
  `git commit -F -` rather than retyping trailers.
- After committing, attach the hash: `greenhouse session commit <session-id>`
  (resolves `HEAD` itself; a sha or any revision may be passed). This writes
  the sha into session/ADR frontmatter and dirties the tree again — commit
  those metadata edits immediately as a follow-up with the subject the command
  prints (`spec(<project>): attach commit hash to session <id>`). Never amend
  the spec commit instead: amending changes the sha that was just recorded.
- Tooling changes: `feat(tooling):` / `fix(tooling):`. Stay on `main` unless
  asked otherwise.

## Execution

- All Python runs through this repo's env: `uv run greenhouse …`, `uv run pytest`.
  Never `pip install`, never system Python.
- `uv run greenhouse check` (validate + lint, warn/error lines only; `--xref`
  adds xref) before any spec commit; fix errors (warnings are judgement calls
  to surface, not silently accept). Mid-drill, a draft may cite the ADR about
  to be written: `check --pending-adr $(uv run greenhouse decision next-id)`.
- Read and replace section prose through `greenhouse section show|write <id>`
  (slice located by the spec-state anchor), not by hand-rolled regex over
  workfiles; `section guidance` and `section deps` answer the LOAD questions.
