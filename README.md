# Greenhouse Concept

An AI-driven workspace for growing raw ideas into clear, consistent product and
technical specifications through iterative exploration, discussion, and
decision-making.

You bring a rough idea; the workspace helps you drill into it over many
sessions — in any order you like — while mechanically tracking what is still
vague, what was decided and why, and what ideas were considered along the way.
You can spec a few CLI commands in fine detail today and leave authentication
completely opaque; next time you return, the workspace will point at the blank
and offer to fill it.

## Quick start

```bash
uv sync          # create the environment
uv run pytest    # verify the tooling
```

Spec projects live in a **workspace** of your own — any folder, normally its
own git repo — so this tooling repo stays shareable and never carries your
specs:

```bash
uv run greenhouse workspace init ~/specs --use   # mark it + point this checkout at it
git -C ~/specs init                              # its own repo (recommended)
uv run greenhouse workspace show                 # what will be used, and why
```

`--use` writes a git-ignored `greenhouse.local.toml` here; the
`GREENHOUSE_WORKSPACE` env var overrides it. With nothing configured, the
`projects/` folder of this checkout is the (git-ignored) fallback workspace.

Open a Claude Code session in this repo, then:

- `/spec-new my-project` — start a new spec (a short interview, then a
  scaffolded project in the workspace).
- `/spec-continue` — resume any time. With one project it is picked up
  automatically; with several you are asked, unless you set a default with
  `uv run greenhouse workspace project <name>`.

## What a session feels like

1. **You're shown where things stand** — a one-line maturity picture and a
   ranked menu: fill this blank, answer this blocking question, re-review that
   stale section, triage ideas, or bring your own topic.
2. **Questions come before prose.** Drilling a section starts with the AI
   restating its understanding for correction, then batched multiple-choice
   questions — a recommended option first, honest trade-offs on each. "I don't
   know yet" is always valid and becomes a recorded open question, never a
   guessed answer.
3. **Then a draft**, with requirements as testable `REQ-…` lines, assumptions
   marked explicitly, and an end-of-drill **"what I did NOT decide"** list.
4. **You sign off** — a section only becomes *agreed* when you say so.
5. **Everything is recorded**: your answers verbatim in a session log, real
   decisions as ADRs, stray ideas into the backlog. The AI commits to git
   after each significant step, so history stays legible.

## How progress is tracked

Each project's `spec-state.yaml` indexes every section of the future spec with
a **maturity**:

| Maturity | Meaning |
|---|---|
| `none` | expected by the template, nothing written yet |
| `stub` | topic named, questions open |
| `draft` | prose exists, unresolved questions remain |
| `agreed` | you explicitly confirmed it; no blocking questions left |
| `locked` | frozen — changing it requires a superseding decision record |

From that index the workspace derives the three signals that drive the
"what's next" menu:

- **Blanks** — sections still at `none`/`stub`.
- **Blockers** — open questions marked *blocking*, ranked by how many
  downstream sections they gate (sections declare `depends_on` edges).
- **Staleness** — a section you agreed on whose *inputs* moved afterwards: a
  dependency section changed, or a registered source file changed on disk.
  This is what keeps a spec consistent even when you work in random order.

You never edit `spec-state.yaml` by hand — the `greenhouse` CLI (and the AI
through it) maintains it, so the index and the prose can't drift apart.

## Inside a project folder

```
~/specs/my-project/
├── spec-state.yaml      # the index: sections, maturity, questions, ideas, sources
├── workfiles/           # work-in-progress prose, freely rewritten (+ IDEAS.md)
├── sources/             # curated input material (docs, transcripts, PDFs)
├── history/
│   ├── decisions/       # ADRs: context, options, choice, consequences
│   ├── sessions/        # session logs with your answers verbatim
│   └── references/      # cached extractions from links/files read mid-session
└── final/               # promoted shards + generated SPEC.md + deliverables/
```

**The flow:** `sources/` (input, never ships) → `workfiles/` (messy, iterated)
→ `history/` (why things were chosen, append-only) → `final/` (only agreed
content, generated — never hand-edited).

`history/` and git are complementary, not redundant: git records *what bytes
changed*; `history/` records *what was decided and why*, id-linked so the AI
re-reads it instead of re-litigating settled questions.

**Sources vs. references** — two kinds of external material, kept distinct:

| | `sources/` | `history/references/` |
|---|---|---|
| Holds | the original material, verbatim | a distilled extraction the AI wrote |
| Comes from | deliberately curated by you (`/spec-source`) | a link or file handed over mid-session |
| Exists so that | the project's foundations are on file | the same page is never re-read/re-fetched |
| Goes stale | when you replace it (checksum-tracked) | volatile entries expire and get re-fetched |

Both are citable while drafting and **barred from `final/`**: promotion strips
every citation and a fail-closed leak check aborts if any internal id or path
would ship. Facts a reader needs get restated in the spec's own words (public
URLs may appear in a References section; internal documents never).

## Ideas are never lost — or invented twice

Anything promising that surfaces mid-session lands in the project's idea
backlog (`workfiles/IDEAS.md`, indexed in state) instead of dying with the
conversation. Each idea moves through
`open → deferred / accepted / rejected / superseded / obsolete`, where
*accepted* requires an actual decision record and *rejected* requires a reason.
Near-duplicates are refused at entry — proposing something close to a
previously rejected idea resurfaces the old rejection reason, so reversals are
conscious. Audits flag ideas whose target sections changed or got locked, and
`/spec-idea` (with no topic) walks you through triage.

## Asking "why is it like this?"

Every artifact — sections, questions, ideas, decisions, sources, requirements —
has a stable id, and everything cross-links. `/spec-trace <id>` reconstructs
the complete story of any part: what was asked and answered (your words, not a
paraphrase), which options were considered and why the losers lost, what
superseded what, and where it stands now. Re-opening a settled topic always
starts from that record, so you're never re-asked what you already answered.

## Commands

| Command | What it does |
|---|---|
| `/spec-new <name>` | Start a new project (short interview + scaffold) |
| `/spec-continue` | Resume: gaps, stale sections, open questions, idea triage |
| `/spec-drill [section]` | The core loop: questions first, then a draft, then your sign-off |
| `/spec-idea [topic]` | Generate fresh alternatives, or triage the idea backlog |
| `/spec-review [section]` | Critique for contradictions, gaps, and drift |
| `/spec-decide [section]` | Record a decision as an ADR and mark the section agreed |
| `/spec-trace <id>` | Reconstruct the full reasoning history of any part |
| `/spec-source <path\|url>` | Register input material |
| `/spec-finalize` | Promote agreed sections to `final/` and build `SPEC.md` |
| `/spec-archetype <name>` | Design a new project archetype (see Templates below) |
| `/spec-trello [sync\|setup\|status]` | Mirror the project onto a read-only Trello dashboard board |

Under the hood the **`greenhouse` CLI** (Python, managed with
[uv](https://docs.astral.sh/uv/)) does the mechanical work: coverage/gap
reports, validation, linting, cross-reference checks, idea dedupe, trace
reconstruction, and the source-leak barrier. `uv run greenhouse --help` lists
everything; every command resolves its project from your working directory,
with `--project <name>` as the override.

An MCP server (`greenhouse-mcp`, registered in `.mcp.json`) exposes the same
state to any MCP client: project listing, coverage, open questions, trace,
and document export through the integrations seam.

## Templates: the kinds of things you can spec

`templates/` defines the project **archetypes** — the blueprints `/spec-new`
scaffolds from. This is the main extension point of the workspace: to spec a
new *kind* of thing, you add an archetype here, no code changes needed.

Each archetype is two files sharing a stem:

- **`templates/taxonomies/<archetype>.yaml`** *(required)* — the expected
  section tree: section ids, titles, which workfile each lives in, and
  `depends_on` edges. This is what powers the whole "come back later" loop —
  coverage can only report *"auth is still blank"* because the taxonomy
  declared that this kind of spec ought to have an auth section, and the
  dependency edges drive blocker ranking and staleness propagation. The same
  file declares the archetype's **deliverables** — what finalization hands
  over beyond `SPEC.md` (an operator guide, a Terraform brief and an
  architecture diagram for a deployment; a formal command reference for a
  CLI), each with a description of what it must contain and the sections
  that feed it. `/spec-new` re-verifies that list per project, drills see
  which deliverables a section feeds (`greenhouse section guidance`),
  coverage reports readiness and staleness, and `/spec-finalize` writes the
  files under `final/deliverables/` (`greenhouse deliverable write`, leak-
  checked like everything else under `final/`).
- **`templates/docs/<archetype>.yaml`** *(optional)* — per-section drafting
  guidance: one sentence on what a complete version of each section covers.
  Inserted as `<!-- guidance: -->` comments at scaffold time; the drill loop
  and the spec-critic use it as the local definition of "complete", and the
  bundle strips it from `final/`.

Shipped archetypes: `cli-tool`, `service`, `library`, `platform-deployment`,
`saas-hld` — each with its deliverables declared.

**To add one**: run `/spec-archetype <name>` — the AI designs the section
tree, dependencies and deliverables with you, writes both files, and
verifies them by scaffolding a throwaway project. By hand: copy the closest existing taxonomy,
reshape its sections and `depends_on` edges, write the matching guidance
file, then `uv run greenhouse new demo --archetype <name>` +
`uv run greenhouse validate` to prove the scaffold is coherent. Either way,
changes affect only *newly created* projects — existing `spec-state.yaml`
files are never rewritten by template edits.

## Deliberately not built (yet)

- Real exporters to Notion / Obsidian / Trello / Asana — the protocol and a
  reference implementation exist (`src/greenhouse/integrations/README.md`
  has the recipe); Obsidian is the recommended first one.
- Diagram generation inside specs; a shared glossary across projects;
  multi-agent judge panels for big design decisions; publishing specs as
  shareable web pages.
