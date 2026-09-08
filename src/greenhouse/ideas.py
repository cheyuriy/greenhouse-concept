"""Idea backlog: add with near-duplicate refusal, status flow,
relevance audit, and IDEAS.md ↔ spec-state.yaml sync in one operation."""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap

from . import mdutil
from .models import DuplicateError, GreenhouseError
from .state import today

if TYPE_CHECKING:
    from .models import SpecState
    from .state import Project

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "can", "do", "each",
    "every", "for", "from", "in", "into", "is", "it", "of", "on", "or", "our",
    "per", "should", "so", "than", "that", "the", "their", "this", "to", "use",
    "via", "we", "when", "with", "would",
}

AGING_DAYS = 120  # open ideas untouched this long get flagged by audit
SIMILARITY_THRESHOLD = 0.6


def fingerprint(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9-]+", text.lower())
    return sorted({t for t in tokens if t not in _STOPWORDS and len(t) > 2})


def similarity(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_near_duplicate(spec: SpecState, title: str) -> tuple[str, float] | None:
    """(existing idea id, score) of the closest near-duplicate, any status."""
    fp = fingerprint(title)
    best: tuple[str, float] | None = None
    for idea in spec.ideas:
        score = similarity(fp, idea.fingerprint or fingerprint(idea.title))
        if score >= SIMILARITY_THRESHOLD and (best is None or score > best[1]):
            best = (idea.id, score)
    return best


# ---------------------------------------------------------------------------
# Mutations (always update state + IDEAS.md together)
# ---------------------------------------------------------------------------


def add_idea(
    project: Project,
    title: str,
    body: str = "",
    relates_to: list[str] | None = None,
    source: str = "user",
    allow_duplicate: bool = False,
    date: dt.date | None = None,
) -> str:
    """Register an idea; refuses silent near-duplicates regardless of status
    (a rejected twin is re-surfaced with its rejection reason)."""
    spec = project.spec()
    date = date or today()
    relates_to = relates_to or []
    for rel in relates_to:
        if not spec.section_by_id(rel):
            raise GreenhouseError(f"relates_to section {rel!r} does not resolve")

    dup = find_near_duplicate(spec, title)
    if dup and not allow_duplicate:
        existing = spec.idea_by_id(dup[0])
        detail = f"{existing.id} ({existing.status})"
        if existing.status in ("rejected", "obsolete") and existing.resolution:
            detail += f" — rejected because: {existing.resolution}"
        raise DuplicateError(
            f"Near-duplicate of {detail}: {existing.title!r} "
            f"(similarity {dup[1]:.0%}). Pass --allow-duplicate to add anyway, "
            f"or cite {existing.id} instead."
        )

    idea_id = project.next_idea_id()
    heading = f"{idea_id}: {title}"
    anchor = mdutil.slugify(heading)

    entry = CommentedMap()
    entry["id"] = idea_id
    entry["title"] = title
    entry["status"] = "open"
    entry["relates_to"] = list(relates_to)
    entry["source"] = source
    entry["raised"] = date
    entry["ref"] = f"workfiles/IDEAS.md#{anchor}"
    entry["fingerprint"] = fingerprint(title)
    entry["resolution"] = None
    entry["last_checked"] = date
    project._raw_list("ideas").append(entry)

    for rel in relates_to:
        project.link_idea_to_section(rel, idea_id)

    _append_ideas_md(project, idea_id, title, source, date, relates_to, body)
    project.save()
    return idea_id


def set_status(
    project: Project,
    idea_id: str,
    status: str,
    resolution: str | None = None,
    date: dt.date | None = None,
) -> None:
    """Move an idea through its lifecycle. `accepted` requires an ADR id;
    rejected/obsolete/superseded require a reason."""
    valid = ("open", "deferred", "accepted", "rejected", "superseded", "obsolete")
    if status not in valid:
        raise GreenhouseError(f"Invalid status {status!r}; one of {', '.join(valid)}")
    if status == "accepted" and not (resolution and re.fullmatch(r"\d{4}", resolution)):
        raise GreenhouseError(
            "accepted requires --resolution <ADR id> (e.g. 0003); "
            "nothing is accepted without a decision record"
        )
    if status in ("rejected", "obsolete", "superseded") and not resolution:
        raise GreenhouseError(f"{status} requires --resolution with the reason")

    raw = project.raw_idea(idea_id)
    raw["status"] = status
    raw["resolution"] = resolution
    raw["last_checked"] = date or today()
    _update_ideas_md_status(project, idea_id, status, resolution)
    project.save()


def mark_checked(project: Project, idea_id: str, date: dt.date | None = None) -> None:
    project.raw_idea(idea_id)["last_checked"] = date or today()
    project.save()


# ---------------------------------------------------------------------------
# Audit + sync (keep ideas relevant to the moving spec)
# ---------------------------------------------------------------------------


def audit(project: Project, spec: SpecState | None = None) -> list[dict[str, Any]]:
    """Mechanical relevance flags on open/deferred ideas; the consistency-auditor
    turns these into judgment calls, the user confirms."""
    spec = spec or project.spec()
    findings: list[dict[str, Any]] = []
    now = today()
    for idea in spec.ideas:
        if idea.status not in ("open", "deferred"):
            continue
        for rel in idea.relates_to:
            sec = spec.section_by_id(rel)
            if sec is None:
                findings.append(
                    {"idea": idea.id, "kind": "orphaned",
                     "detail": f"relates_to {rel!r} no longer exists"}
                )
                continue
            if (
                idea.last_checked
                and sec.last_touched
                and sec.last_touched > idea.last_checked
            ):
                findings.append(
                    {"idea": idea.id, "kind": "stale-relevance",
                     "detail": f"section {sec.id} changed after last_checked "
                               f"({sec.last_touched} > {idea.last_checked})"}
                )
            if sec.maturity == "locked":
                findings.append(
                    {"idea": idea.id, "kind": "target-locked",
                     "detail": f"section {sec.id} is locked; idea needs an ADR to proceed"}
                )
        if idea.raised and (now - idea.raised).days > AGING_DAYS:
            findings.append(
                {"idea": idea.id, "kind": "aging",
                 "detail": f"open since {idea.raised} with no movement"}
            )
    return findings


def sync_problems(project: Project) -> list[str]:
    """IDEAS.md and the state index must never disagree."""
    problems: list[str] = []
    spec = project.spec()
    text = project.ideas_file.read_text() if project.ideas_file.exists() else ""
    for idea in spec.ideas:
        block = _idea_block(text, idea.id)
        if block is None:
            problems.append(f"{idea.id}: missing section in IDEAS.md")
            continue
        m = re.search(r"\*\*Status:\*\*\s*(\w+)", block)
        if not m:
            problems.append(f"{idea.id}: no Status line in IDEAS.md")
        elif m.group(1) != idea.status:
            problems.append(
                f"{idea.id}: IDEAS.md says {m.group(1)!r}, state says {idea.status!r}"
            )
    ids = {i.id for i in spec.ideas}
    for m in re.finditer(r"^## (idea-\d{4})", text, re.MULTILINE):
        if m.group(1) not in ids:
            problems.append(f"{m.group(1)}: in IDEAS.md but not in spec-state.yaml")
    return problems


# ---------------------------------------------------------------------------
# IDEAS.md maintenance
# ---------------------------------------------------------------------------


def _append_ideas_md(
    project: Project,
    idea_id: str,
    title: str,
    source: str,
    date: dt.date,
    relates_to: list[str],
    body: str,
) -> None:
    text = project.ideas_file.read_text() if project.ideas_file.exists() else "# Idea backlog\n"
    section = [
        "",
        f"## {idea_id}: {title}",
        "",
        "- **Status:** open",
        f"- **Relates to:** {', '.join(relates_to) if relates_to else '—'}",
        f"- **Source:** {source} ({date})",
        "",
        body.strip() or "_No elaboration yet._",
        "",
    ]
    project.ideas_file.write_text(text.rstrip() + "\n" + "\n".join(section))


def _idea_block(text: str, idea_id: str) -> str | None:
    m = re.search(rf"^## {re.escape(idea_id)}:.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else None


def _update_ideas_md_status(
    project: Project, idea_id: str, status: str, resolution: str | None
) -> None:
    text = project.ideas_file.read_text() if project.ideas_file.exists() else ""
    block = _idea_block(text, idea_id)
    if block is None:
        raise GreenhouseError(f"{idea_id} has no section in IDEAS.md (index drift)")
    new_block = re.sub(r"- \*\*Status:\*\*.*", f"- **Status:** {status}", block, count=1)
    if resolution:
        label = "Decision" if status == "accepted" else "Resolution"
        line = f"- **{label}:** {resolution}"
        if re.search(r"- \*\*(Decision|Resolution):\*\*.*", new_block):
            new_block = re.sub(r"- \*\*(Decision|Resolution):\*\*.*", line, new_block, count=1)
        else:
            new_block = re.sub(
                r"(- \*\*Status:\*\*.*)", r"\1\n" + line, new_block, count=1
            )
    project.ideas_file.write_text(text.replace(block, new_block))
