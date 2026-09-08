"""Small shared markdown/frontmatter helpers used across the tooling.

Kept internal: heading parsing + slugs (workfile anchors), provenance/reference
marker extraction, and YAML frontmatter round-tripping for history files.
"""

from __future__ import annotations

import io
import re
from typing import Any

from markdown_it import MarkdownIt
from ruamel.yaml import YAML

_yaml = YAML(typ="rt")
_yaml.default_flow_style = False

_md = MarkdownIt("commonmark")

# ---------------------------------------------------------------------------
# Headings and anchors
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """GitHub-style heading slug: lowercase, drop punctuation, spaces → hyphens."""
    text = text.strip().lower()
    text = re.sub(r"[`*_~]", "", text)  # inline markup
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text.strip("-")


def parse_headings(text: str) -> list[dict[str, Any]]:
    """Return [{level, text, slug, line}] for every heading, 0-based line numbers."""
    headings: list[dict[str, Any]] = []
    tokens = _md.parse(text)
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.map:
            inline = tokens[i + 1]
            title = inline.content if inline.type == "inline" else ""
            headings.append(
                {
                    "level": int(tok.tag[1]),
                    "text": title,
                    "slug": slugify(title),
                    "line": tok.map[0],
                }
            )
    return headings


def anchors_in(text: str) -> set[str]:
    """All addressable anchors in a document: heading slugs + explicit <a id=…>."""
    anchors = {h["slug"] for h in parse_headings(text)}
    anchors.update(re.findall(r'<a\s+id="([^"]+)"', text))
    return anchors


def extract_section_slice(text: str, anchor: str) -> str | None:
    """The lines from the heading matching `anchor` up to the next heading of the
    same or higher level. None if the anchor is not a heading in this document."""
    headings = parse_headings(text)
    lines = text.splitlines()
    for idx, h in enumerate(headings):
        if h["slug"] == anchor:
            end = len(lines)
            for nxt in headings[idx + 1:]:
                if nxt["level"] <= h["level"]:
                    end = nxt["line"]
                    break
            return "\n".join(lines[h["line"]:end]).rstrip() + "\n"
    return None


# ---------------------------------------------------------------------------
# Provenance / reference markers — `why:` cites internal reasoning (ADRs,
# ideas), `ref:` cites external material (sources, cached references); only
# `ref:` ids are leak-checked out of final/. See CLAUDE.md.
# ---------------------------------------------------------------------------

WHY_MARKER_RE = re.compile(r"<!--\s*why:\s*([^>]*?)-->")
REF_MARKER_RE = re.compile(r"<!--\s*ref:\s*([^>]*?)-->")

# ids that may appear inside markers
ADR_ID_RE = re.compile(r"(?<![\w-])(\d{4})\b")  # not the digits of idea-/src-/ref- ids
IDEA_ID_RE = re.compile(r"\b(idea-\d{4})\b")
SRC_ID_RE = re.compile(r"\b(src-\d{4})\b")
REF_ID_RE = re.compile(r"\b(ref-\d{4})\b")
REQ_ID_RE = re.compile(r"\bREQ-([A-Z0-9]+(?:-[A-Z0-9]+)*)-(\d{3})\b")
BOLD_REQ_RE = re.compile(r"\*\*(REQ-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3})\*\*")  # a *definition*, vs a prose mention


def extract_why_ids(text: str) -> list[tuple[int, str]]:
    """(0-based line, id) for every id cited in a `why:` marker (ADRs, ideas)."""
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines()):
        for m in WHY_MARKER_RE.finditer(line):
            body = m.group(1)
            out.extend((lineno, i) for i in IDEA_ID_RE.findall(body))
            out.extend((lineno, i) for i in ADR_ID_RE.findall(body))
    return out


def extract_ref_ids(text: str) -> list[tuple[int, str]]:
    """(0-based line, id) for every src-/ref- id cited in a `ref:` marker."""
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines()):
        for m in REF_MARKER_RE.finditer(line):
            body = m.group(1)
            out.extend((lineno, i) for i in SRC_ID_RE.findall(body))
            out.extend((lineno, i) for i in REF_ID_RE.findall(body))
    return out


def strip_markers(text: str, why: bool = True, ref: bool = True) -> str:
    """Remove marker comments (used when promoting to final/)."""
    if ref:
        text = REF_MARKER_RE.sub("", text)
    if why:
        text = WHY_MARKER_RE.sub("", text)
    # tidy trailing whitespace the removals leave behind
    return re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split a markdown document into (frontmatter dict | None, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    data = _yaml.load(m.group(1))
    return (dict(data) if data else {}), text[m.end():]


def dump_frontmatter(data: dict[str, Any], body: str) -> str:
    buf = io.StringIO()
    _yaml.dump(data, buf)
    return f"---\n{buf.getvalue()}---\n\n{body.lstrip()}" if body.strip() else f"---\n{buf.getvalue()}---\n"
