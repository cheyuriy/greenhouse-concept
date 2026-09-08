"""Section slices: read and replace one section's prose in its workfile.

A section's slice runs from its heading (located by the `workfile#anchor`
recorded in spec-state.yaml, never by matching the title text) up to the next
heading of the same or a higher level. `write` replaces exactly that range,
keeps the `<!-- guidance: -->` comment if the new text dropped it, and refuses
a heading that does not resolve to the section's anchor.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import deliverables as deliverables_mod
from . import mdutil
from .models import GreenhouseError

if TYPE_CHECKING:
    from .state import Project

GUIDANCE_RE = re.compile(r"<!--\s*guidance:\s*(.*?)\s*-->", re.DOTALL)


def locate(project: Project, section_id: str) -> dict[str, Any]:
    """{section, path, anchor, level, start, end, lines} — `start`/`end` are
    0-based line bounds of the slice (end exclusive) in `lines`."""
    spec = project.spec()
    sec = spec.section_by_id(section_id)
    if sec is None:
        raise GreenhouseError(f"Unknown section: {section_id}")
    if not sec.workfile:
        raise GreenhouseError(f"Section {sec.id} has no workfile")
    rel, _, anchor = sec.workfile.partition("#")
    path = project.root / rel
    if not path.exists():
        raise GreenhouseError(f"Section {sec.id}: workfile {rel!r} missing")
    if not anchor:
        raise GreenhouseError(f"Section {sec.id}: workfile {rel!r} carries no #anchor")
    text = path.read_text()
    lines = text.splitlines()
    headings = mdutil.parse_headings(text)
    for idx, h in enumerate(headings):
        if h["slug"] == anchor:
            end = len(lines)
            for nxt in headings[idx + 1:]:
                if nxt["level"] <= h["level"]:
                    end = nxt["line"]
                    break
            return {
                "section": sec.id, "path": path, "rel": rel, "anchor": anchor,
                "level": h["level"], "heading": h["text"],
                "start": h["line"], "end": end, "lines": lines,
            }
    raise GreenhouseError(f"Section {sec.id}: anchor #{anchor} not found in {rel}")


def show(project: Project, section_id: str) -> str:
    loc = locate(project, section_id)
    return "\n".join(loc["lines"][loc["start"]:loc["end"]]).rstrip() + "\n"


def guidance(project: Project, section_id: str) -> str | None:
    """The drafting guidance recorded under the section's heading, if any."""
    m = GUIDANCE_RE.search(show(project, section_id))
    return " ".join(m.group(1).split()) if m else None


def deps(project: Project, section_id: str) -> dict[str, Any]:
    """Upstream chain (transitive, nearest first), dependents (direct and
    transitive) with their maturity — the reverse edges spec-state never
    lists — and the deliverables this section feeds."""
    spec = project.spec()
    sec = spec.section_by_id(section_id)
    if sec is None:
        raise GreenhouseError(f"Unknown section: {section_id}")
    maturity = {s.id: s.maturity for s in spec.sections}

    upstream: list[str] = []
    frontier = list(sec.depends_on)
    while frontier:
        dep = frontier.pop(0)
        dep_c = spec.canonical_section_id(dep) or dep
        if dep_c in upstream or dep_c == sec.id:
            continue
        upstream.append(dep_c)
        parent = spec.section_by_id(dep_c)
        if parent:
            frontier.extend(parent.depends_on)

    def rows(ids: list[str]) -> list[dict[str, str]]:
        return [{"section": i, "maturity": maturity.get(i, "?")} for i in ids]

    direct = spec.dependents_of(sec.id, transitive=False)
    transitive = [d for d in spec.dependents_of(sec.id) if d not in direct]
    return {
        "section": sec.id,
        "maturity": sec.maturity,
        "depends_on": rows(list(sec.depends_on)),
        "upstream": rows(upstream),
        "dependents": rows(direct),
        "transitive_dependents": rows(transitive),
        "deliverables": deliverables_mod.for_section(spec, sec.id),
    }


def write(
    project: Project, section_id: str, new_text: str, dry_run: bool = False,
) -> str:
    """Replace the section's slice with `new_text`; returns a unified diff.
    Refuses when the new text's first heading is not this section's heading."""
    loc = locate(project, section_id)
    new_lines = new_text.rstrip("\n").splitlines()
    new_headings = mdutil.parse_headings(new_text)
    if not new_headings or new_headings[0]["line"] != _first_content_line(new_lines):
        raise GreenhouseError(
            f"New text must start with the section heading "
            f"'{'#' * loc['level']} {loc['heading']}'"
        )
    head = new_headings[0]
    if head["slug"] != loc["anchor"] or head["level"] != loc["level"]:
        raise GreenhouseError(
            f"Heading mismatch: expected '{'#' * loc['level']} {loc['heading']}' "
            f"(#{loc['anchor']}), got '{'#' * head['level']} {head['text']}'"
        )
    for h in new_headings[1:]:
        if h["level"] <= loc["level"]:
            raise GreenhouseError(
                f"New text contains a heading of level {h['level']} ('{h['text']}') that "
                f"would end the section early; only deeper headings are allowed inside"
            )

    old_slice = "\n".join(loc["lines"][loc["start"]:loc["end"]])
    old_guidance = GUIDANCE_RE.search(old_slice)
    if old_guidance and not GUIDANCE_RE.search(new_text):
        insert_at = head["line"] + 1
        block = ["", old_guidance.group(0)]
        if insert_at < len(new_lines) and new_lines[insert_at].strip():
            block.append("")
        new_lines[insert_at:insert_at] = block

    # keep exactly one blank line before whatever follows the slice
    tail = loc["lines"][loc["end"]:]
    body = [*new_lines, ""] if tail else new_lines
    updated = [*loc["lines"][:loc["start"]], *body, *tail]
    new_full = "\n".join(updated).rstrip("\n") + "\n"
    old_full = "\n".join(loc["lines"]).rstrip("\n") + "\n"
    diff = "".join(
        difflib.unified_diff(
            old_full.splitlines(keepends=True), new_full.splitlines(keepends=True),
            fromfile=f"a/{loc['rel']}", tofile=f"b/{loc['rel']}",
        )
    )
    if not dry_run and new_full != old_full:
        Path(loc["path"]).write_text(new_full)
    return diff


def _first_content_line(lines: list[str]) -> int:
    for i, ln in enumerate(lines):
        if ln.strip():
            return i
    return -1
