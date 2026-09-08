---
name: spec-source
description: Register input material (a file, doc, transcript, or URL) as a project source — indexed, checksummed, confidentiality-flagged — then summarise what it contributes and which sections it touches. Use when the user shares reference material the spec should be built on.
argument-hint: <path-or-url>
---

# /spec-source — take in material

Resolve the project (CLAUDE.md), echo it.

## 1. Read it first

Read the file (or fetch the URL — `greenhouse ref lookup` first, per
CLAUDE.md) **before** registering: you must know what it is to index it
honestly, and to summarise it afterwards.

## 2. Ask what it is

One AskUserQuestion batch:
- **What is this?** — offer your inferred title + kind (file/url/note/transcript).
- **Confidential?** — if yes, verbatim quoting beyond a short run is
  lint-forbidden; the spec extracts facts instead. Recommend *yes* for
  anything internal (interviews, internal docs).
- **Relates to** — your best guess at section ids (multiSelect).

## 3. Register

```bash
uv run greenhouse source add <path-or-url> --title "<t>" [--confidential] \
  [--relates <s> ...] --note "<why it matters>"
```

Files are copied into `sources/`; INDEX.md regenerates. For a URL whose
*content* matters now, also cache the extraction:
`uv run greenhouse ref add <url> --title ... --body "<extraction + Not extracted list>"`.

## 4. Summarise the contribution

Tell the user, briefly: what this source answers that was open (name the
question ids it could resolve), what it contradicts in the current spec (if
anything — that's a review flag), and what it newly raises. Then one
AskUserQuestion: drill one of the touched sections now with this source in
hand, or stop.

## 5. Commit

`spec(<project>): add source — <title>` (registration alone is commit-worthy;
include the session trailer only if a drill followed).
