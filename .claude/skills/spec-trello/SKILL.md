---
name: spec-trello
description: Mirror a project's spec state onto its Trello board as a read-only dashboard — one card per section, open/answered question and idea, created and moved between lists as maturity and questions change. Use when the user asks to sync, update, set up, or check the Trello board for a project, and automatically after a spec commit when spec-state.yaml has trello.enabled.
argument-hint: "[sync|setup|status] [project]"
---

# /spec-trello — the read-only dashboard

Trello shows progress; it never decides anything. Direction is strictly
spec state → board (CLAUDE.md "Trello dashboard"). Concretely:

- The **only** write to the tree this skill ever makes is
  `greenhouse trello configure` (board name, enabled flag, board URL).
- Never call `greenhouse state|idea|session|decision …` from here, and never
  turn something seen on a card into a state change. If a card looks edited
  by hand, the next sync overwrites it — say so, don't merge.
- Card identity is the `[<id>]` prefix of the card name (regex
  `^\[([A-Za-z0-9_.:-]+)\]`). Cards without that marker and lists the plan
  does not name are the user's: never edit, move, or archive them.
- Lists are never archived or renamed by this skill, even plan lists.

Modes (first argument; default `sync`): `setup` configures the board,
`sync` reconciles it, `status` reads the board and reports drift without
writing anything to Trello.

## 1. Resolve and gate

Resolve the project per CLAUDE.md, echo `Project: <name> (<how>)`, then:

```bash
uv run greenhouse trello show --json     # exit 3 = no trello: block
```

- No block → run **setup** (§2) if the user asked for it or for a sync;
  otherwise say the project has no dashboard and stop.
- `enabled: false` → say so and stop, unless the user explicitly asks to
  enable it (then `trello configure --enable`, commit as in §2).
- Enabled → continue with the requested mode.

## 2. Setup (once per project)

One AskUserQuestion, 2–3 questions:

1. Board name — recommended: the project `title` from spec-state (the plan
   uses it too); the user may name an existing board instead.
2. Create the board if it does not exist? (recommended yes, `PRIVATE`
   visibility) — or only use an existing one.
3. Workspace, only if `trelloReadWorkspace list` returns more than one.

Then record it and commit on its own (no session log — nothing about the
spec was decided):

```bash
uv run greenhouse trello configure --board "<exact name>" --enable
ROOT="$(uv run greenhouse root)"; DIR="$(uv run greenhouse root --project-dir)"
uv run greenhouse check
git -C "$ROOT" add "$DIR" && git -C "$ROOT" commit -q -m 'spec(<project>): configure trello dashboard "<exact name>"'
```

Continue straight into a sync.

## 3. Sync

### 3a. Get the plan

```bash
uv run greenhouse trello plan --json > "$SCRATCH/trello-plan.json"
```

The plan is the whole desired board: `lists` (display order), `cards`
(`id`, `kind`, `list`, `name`, `desc`, `pos`, `labels`, optional
`preserve_name`), `retire_to` (where a card of each kind goes once its id has
left the plan), `board`, `board_url`. Read it from the file; do not
recompute any of it by hand.

### 3b. Locate the board

- `board_url` recorded → `trelloReadBoard get` with that URL. If it is
  closed or gone, fall through to the name search and re-record.
- Otherwise `trelloSearch search_boards` with the exact name (`partial`
  false) and keep only results whose `name` equals `board` exactly;
  `trelloReadBoard list` is the fallback when search returns nothing.
  - exactly one → use it;
  - none → `trelloWriteBoard create` (name = `board`, `PRIVATE`, the sole
    workspace or the one chosen in setup); `prefs.cardCounts: true`;
  - several → AskUserQuestion listing their URLs. Never guess.
- Whenever the URL was not recorded yet (or changed), record it and commit:

  ```bash
  uv run greenhouse trello configure --url "<board url>"
  git -C "$ROOT" add "$DIR" && git -C "$ROOT" commit -q -m 'spec(<project>): record trello board url'
  ```

Use the board **ARI** (`id` from the read) for every later call; URLs are
only for `get`.

### 3c. Lists

`trelloReadList list_by_board` (paginate until `hasNextPage` is false). For
each name in `plan.lists` missing on the board, `trelloWriteList create`
with `pos` = its index + 1 in `plan.lists`; independent creates go out in
parallel. Existing lists keep their position and name. Build
`list_name → list ARI`.

### 3d. Read the cards

`trelloReadCard list_by_board` with `filter: "open"`, paginating over
lists. For every card, parse the id with the regex above; index
`id → {card ARI, list name, name, desc, labels}`. Cards with no marker are
ignored for the rest of the sync.

### 3e. Reconcile (plan → board)

For each plan card, in plan order:

- **missing** → `trelloWriteCard create` on the target list with `name`,
  `desc`, `pos`.
- **present, wrong list** → `trelloWriteCard move` to the target list with
  `pos`.
- **present** and `desc` differs, or `name` differs and the plan card has no
  `preserve_name` → `trelloWriteCard update` (only the changed fields).
  `preserve_name` cards (answered questions) keep the name the card had while
  the question was open — the text lives nowhere else once it leaves
  spec-state.
- Otherwise nothing.

Then retire: every board card with a marker whose id is **not** in the plan
→ look up `plan.retire_to[kind]` with `kind` from the id shape (`q-` →
question, `idea-` → idea, `status` → status, anything else → section):
a list name → move it there if it is not already there (name and desc
untouched); `null` → `trelloWriteCard archive`.

Batch independent writes (about ten per turn); one card's create/move/update
never depends on another's. If a write's result is lost or ambiguous, re-read
that list before retrying — never create a second card for the same id.

### 3f. Labels (best effort)

`trelloReadBoard list_labels` once. The MCP server cannot create labels, so
attach only labels whose board `name` matches a plan label name exactly
(`blocking`, `stale`, `section`, `idea`, `deferred`); detach `blocking` and
`stale` from marked cards that no longer list them. If the board has none of
these labels, skip this step and tell the user once that adding them in the
board menu (red `blocking`, yellow `stale`) will light the cards up on the
next sync.

### 3g. Report

Board URL (verbatim), then counts on one line each: created, moved, updated,
retired, unchanged; the status card's headline (`N/M agreed`, blocking and
open question counts); labels skipped or applied. Confirm the tree is clean:
`git -C "$ROOT" status --short` prints nothing (a sync writes nothing;
the URL commit from §3b is the only allowed exception).

## 4. Status (no Trello writes)

Steps 3a, 3b (no create, no URL recording), 3c without creating, and 3d.
Report drift only: plan cards missing from the board, cards on the wrong
list, marked cards no longer in the plan, and cards whose desc differs.
Offer a sync as the next step; do not start one.

## Failure handling

- The `trello` MCP tools missing or unauthenticated → say so and stop; the
  spec work is unaffected and nothing needs a commit.
- Never fake a result: a board or card that was not created is reported as
  not created.
