"""history/: frontmatter readers, the known-id inventory, and the writers for
session logs and ADRs — every file id-linked, back-links
applied to spec-state.yaml automatically, INDEX.md regenerated on write."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import mdutil
from .models import GreenhouseError

if TYPE_CHECKING:
    from .models import SpecState
    from .state import Project

# frontmatter list-fields → the id kind they contain
LINK_FIELDS: dict[str, str] = {
    "sections": "section",
    "sections_touched": "section",
    "ideas": "idea",
    "ideas_raised": "idea",
    "ideas_resolved": "idea",
    "decisions": "decision",
    "supersedes": "decision",
    "questions_asked": "question",
    "questions_resolved": "question",
}

# frontmatter scalar-fields → id kind
SCALAR_LINK_FIELDS: dict[str, str] = {
    "session": "session",
    "retrieved_in": "session",
    "superseded_by": "decision",
}


def _history_files(project: Project) -> list[Path]:
    files: list[Path] = []
    for sub in ("decisions", "sessions", "references"):
        d = project.history_dir / sub
        if d.exists():
            files.extend(sorted(d.glob("*.md")))
    return files


def iter_history_frontmatter(project: Project) -> Iterator[tuple[Path, dict[str, Any]]]:
    """(path, frontmatter) for every history file that has frontmatter."""
    for path in _history_files(project):
        fm, _ = mdutil.parse_frontmatter(path.read_text())
        if fm is not None:
            yield path, fm


def adr_ids(project: Project) -> set[str]:
    """ADR ids from history/decisions/ filenames (NNNN-slug.md)."""
    ids: set[str] = set()
    if project.decisions_dir.exists():
        for f in project.decisions_dir.glob("*.md"):
            head = f.name.split("-", 1)[0]
            if head.isdigit():
                ids.add(head)
    return ids


def session_ids(project: Project) -> set[str]:
    """Session ids from history/sessions/ filenames (YYYY-MM-DD-slug.md)."""
    if not project.sessions_dir.exists():
        return set()
    return {f.stem for f in project.sessions_dir.glob("*.md")}


def reference_ids(project: Project) -> set[str]:
    """ref-NNNN ids from history/references/ filenames."""
    ids: set[str] = set()
    if project.references_dir.exists():
        for f in project.references_dir.glob("ref-*.md"):
            parts = f.name.split("-")
            if len(parts) >= 2 and parts[1].isdigit():
                ids.add(f"ref-{parts[1]}")
    return ids


def historical_question_ids(project: Project) -> set[str]:
    """Question ids recorded by any session log (resolved questions leave the
    state file, but the session that asked them is their permanent record)."""
    ids: set[str] = set()
    for _, fm in iter_history_frontmatter(project):
        for key in ("questions_asked", "questions_resolved"):
            ids.update(str(q) for q in fm.get(key) or [])
    return ids


def req_ids(project: Project) -> set[str]:
    """REQ-SECTION-NNN ids *defined* (bold) across workfiles."""
    ids: set[str] = set()
    if project.workfiles_dir.exists():
        for wf in project.workfiles_dir.glob("*.md"):
            for m in mdutil.BOLD_REQ_RE.finditer(wf.read_text()):
                ids.add(m.group(1))
    return ids


# ---------------------------------------------------------------------------
# Writers  (structured frontmatter + automatic back-links)
# ---------------------------------------------------------------------------


def slugify_for_filename(text: str) -> str:
    return mdutil.slugify(text)[:60].strip("-") or "untitled"


def write_session(
    project: Project,
    slug: str,
    body: str,
    date: dt.date | None = None,
    sections_touched: list[str] | None = None,
    maturity_transitions: list[dict[str, str]] | None = None,
    questions_asked: list[str] | None = None,
    questions_resolved: list[str] | None = None,
    ideas_raised: list[str] | None = None,
    ideas_resolved: list[str] | None = None,
    decisions: list[str] | None = None,
    commits: list[str] | None = None,
) -> str:
    """Write history/sessions/<YYYY-MM-DD-slug>.md and back-link touched
    sections. The body must carry the questions and answers verbatim."""
    from .state import today

    date = date or today()
    session_id = f"{date.isoformat()}-{slugify_for_filename(slug)}"
    path = project.sessions_dir / f"{session_id}.md"
    if path.exists():
        raise GreenhouseError(f"Session {session_id} already exists")

    sections_touched = sections_touched or []
    fm: dict[str, Any] = {
        "id": session_id,
        "type": "session",
        "date": date,
        "sections_touched": sections_touched,
        "maturity_transitions": maturity_transitions or [],
        "questions_asked": questions_asked or [],
        "questions_resolved": questions_resolved or [],
        "ideas_raised": ideas_raised or [],
        "ideas_resolved": ideas_resolved or [],
        "decisions": decisions or [],
        "commits": commits or [],
    }
    project.sessions_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(mdutil.dump_frontmatter(fm, body))

    project.link_session(sections_touched, session_id)
    project.save()
    regenerate_index(project)
    return session_id


def write_decision(
    project: Project,
    title: str,
    body: str,
    sections: list[str],
    date: dt.date | None = None,
    status: str = "accepted",
    ideas: list[str] | None = None,
    questions_resolved: list[str] | None = None,
    supersedes: list[str] | None = None,
    session: str | None = None,
) -> str:
    """Write history/decisions/<NNNN-slug>.md (ADR), back-link its sections,
    and mark any superseded ADRs. Body: context, options, choice, consequences."""
    from .state import today

    date = date or today()
    adr_id = project.next_adr_id()
    path = project.decisions_dir / f"{adr_id}-{slugify_for_filename(title)}.md"

    fm: dict[str, Any] = {
        "id": adr_id,
        "type": "decision",
        "title": title,
        "date": date,
        "status": status,
        "sections": sections,
        "ideas": ideas or [],
        "questions_resolved": questions_resolved or [],
        "supersedes": supersedes or [],
        "superseded_by": None,
        "session": session,
        "commit": None,
    }
    project.decisions_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(mdutil.dump_frontmatter(fm, body))

    for old_id in supersedes or []:
        old_path = decision_path(project, old_id)
        if old_path is None:
            raise GreenhouseError(f"supersedes {old_id!r}: no such ADR")
        old_fm, old_body = mdutil.parse_frontmatter(old_path.read_text())
        old_fm["status"] = "superseded"
        old_fm["superseded_by"] = adr_id
        old_path.write_text(mdutil.dump_frontmatter(old_fm, old_body))

    project.link_decision(sections, adr_id)
    project.save()
    regenerate_index(project)
    return adr_id


def decision_path(project: Project, adr_id: str) -> Path | None:
    if project.decisions_dir.exists():
        for f in project.decisions_dir.glob(f"{adr_id}-*.md"):
            return f
    return None


def session_path(project: Project, session_id: str) -> Path | None:
    p = project.sessions_dir / f"{session_id}.md"
    return p if p.exists() else None


def read_session(project: Project, session_id: str) -> tuple[dict[str, Any], str]:
    """(frontmatter, body) of one session log."""
    path = session_path(project, session_id)
    if path is None:
        raise GreenhouseError(f"No session {session_id!r}")
    fm, body = mdutil.parse_frontmatter(path.read_text())
    return (fm or {}), body


def read_decision(project: Project, adr_id: str) -> tuple[dict[str, Any], str]:
    """(frontmatter, body) of one ADR."""
    path = decision_path(project, adr_id)
    if path is None:
        raise GreenhouseError(f"No ADR {adr_id!r}")
    fm, body = mdutil.parse_frontmatter(path.read_text())
    return (fm or {}), body


def list_sessions(project: Project) -> list[dict[str, Any]]:
    """Session index entries, newest first: id, date, sections, decisions, commits."""
    rows: list[dict[str, Any]] = []
    for path, fm in iter_history_frontmatter(project):
        if fm.get("type") != "session":
            continue
        rows.append(
            {
                "id": str(fm.get("id", path.stem)),
                "date": str(fm.get("date", "")),
                "sections": [str(s) for s in fm.get("sections_touched") or []],
                "decisions": [str(d) for d in fm.get("decisions") or []],
                "commits": [str(c) for c in fm.get("commits") or []],
            }
        )
    rows.sort(key=lambda r: r["id"], reverse=True)
    return rows


def list_decisions(project: Project) -> list[dict[str, Any]]:
    """ADR index entries in id order: id, date, status, title, sections."""
    rows: list[dict[str, Any]] = []
    for path, fm in iter_history_frontmatter(project):
        if fm.get("type") != "decision":
            continue
        rows.append(
            {
                "id": str(fm.get("id", path.stem.split("-", 1)[0])),
                "date": str(fm.get("date", "")),
                "status": str(fm.get("status", "")),
                "title": str(fm.get("title", "")),
                "sections": [str(s) for s in fm.get("sections") or []],
                "commit": fm.get("commit"),
            }
        )
    rows.sort(key=lambda r: r["id"])
    return rows


def commit_message(
    project: Project,
    session_id: str,
    subject: str | None = None,
    trailers: list[str] | None = None,
) -> str:
    """The spec commit message for a session, trailers derived from its
    frontmatter (CLAUDE.md git protocol). The commit itself stays in the skill."""
    fm, body = read_session(project, session_id)
    if not subject:
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        subject = first.lstrip("#").strip() or f"session {session_id}"
    lines = [f"spec({project.name}): {subject}", ""]
    ideas: list[str] = []
    for key in ("ideas_raised", "ideas_resolved"):
        for i in fm.get(key) or []:
            if str(i) not in ideas:
                ideas.append(str(i))
    trailer_rows = [
        ("Sections", [str(s) for s in fm.get("sections_touched") or []]),
        ("Ideas", ideas),
        ("Decisions", [str(d) for d in fm.get("decisions") or []]),
        ("Session", [str(fm.get("id", session_id))]),
    ]
    lines += [f"{key}: {', '.join(vals)}" for key, vals in trailer_rows if vals]
    for extra in trailers or []:
        if ":" not in extra:
            raise GreenhouseError(f"trailer must look like 'Key: value', got {extra!r}")
        lines.append(extra.strip())
    return "\n".join(lines) + "\n"


def attach_commit_subject(project: Project, session_id: str) -> str:
    """Subject of the follow-up commit that carries the recorded sha."""
    return f"spec({project.name}): attach commit hash to session {session_id}"


def record_commit(project: Project, session_id: str, sha: str) -> None:
    """Attach a commit hash to a session log (and its decisions) after committing."""
    path = session_path(project, session_id)
    if path is None:
        raise GreenhouseError(f"No session {session_id!r}")
    fm, body = mdutil.parse_frontmatter(path.read_text())
    commits = list(fm.get("commits") or [])
    if sha not in commits:
        commits.append(sha)
    fm["commits"] = commits
    path.write_text(mdutil.dump_frontmatter(fm, body))
    for adr in fm.get("decisions") or []:
        dpath = decision_path(project, str(adr))
        if dpath:
            dfm, dbody = mdutil.parse_frontmatter(dpath.read_text())
            if not dfm.get("commit"):
                dfm["commit"] = sha
                dpath.write_text(mdutil.dump_frontmatter(dfm, dbody))


def regenerate_index(project: Project) -> None:
    """history/INDEX.md — generated chronological catalogue."""
    rows: list[tuple[str, str, str, str]] = []  # (date, kind, id, title/summary)
    for path, fm in iter_history_frontmatter(project):
        date = str(fm.get("date") or fm.get("retrieved") or "")
        kind = str(fm.get("type", path.parent.name))
        ident = str(fm.get("id", path.stem))
        title = str(fm.get("title", ""))
        if kind == "session" and not title:
            touched = ", ".join(str(s) for s in fm.get("sections_touched") or [])
            title = f"touched: {touched}" if touched else ""
        if kind == "decision":
            title = f"{title} [{fm.get('status', '?')}]"
        rows.append((date, kind, ident, title))
    rows.sort()
    lines = [f"# History — {project.name}", "", "<!-- generated by `greenhouse session log` / history writers -->", ""]
    if not rows:
        lines.append("_No sessions or decisions recorded yet._")
    else:
        lines += ["| date | kind | id | summary |", "|---|---|---|---|"]
        lines += [f"| {d} | {k} | {i} | {t} |" for d, k, i, t in rows]
    (project.history_dir / "INDEX.md").write_text("\n".join(lines) + "\n")


def known_ids(
    project: Project, spec: SpecState, pending_decisions: Iterable[str] = (),
) -> dict[str, set[str]]:
    """Complete id inventory for validation and trace (aliases included).
    `pending_decisions`: ADR ids treated as resolvable for this run only — a
    draft may cite the ADR the drill is about to write (`decision next-id`)."""
    section_ids: set[str] = set()
    for s in spec.sections:
        section_ids.add(s.id)
        section_ids.update(s.aliases)
    open_questions = {q.id for s in spec.sections for q in s.open_questions}
    return {
        "section": section_ids,
        "idea": {i.id for i in spec.ideas},
        "source": {s.id for s in spec.sources},
        "decision": adr_ids(project) | {str(p) for p in pending_decisions},
        "session": session_ids(project),
        "reference": reference_ids(project),
        "question": open_questions | historical_question_ids(project),
        "req": req_ids(project),
    }
