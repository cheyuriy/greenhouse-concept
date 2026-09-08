"""Reasoning reconstruction: `greenhouse trace <id>` walks the
id graph — sessions, ADRs, ideas (rejected ones included), questions, sources,
references, commits — and emits the chronological story of any part."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from . import history, mdutil
from .models import GreenhouseError

if TYPE_CHECKING:
    from .state import Project


def classify(target: str) -> str:
    if re.fullmatch(r"\d{4}", target):
        return "decision"
    if target.startswith("idea-"):
        return "idea"
    if target.startswith("src-"):
        return "source"
    if target.startswith("ref-"):
        return "reference"
    if target.startswith("q-"):
        return "question"
    if mdutil.REQ_ID_RE.fullmatch(target):
        return "req"
    return "section"


def trace(project: Project, target: str) -> dict[str, Any]:
    spec = project.spec()
    kind = classify(target)
    events: list[dict[str, Any]] = []

    def add(date: Any, ekind: str, ident: str, summary: str, **extra: Any) -> None:
        events.append({"date": str(date or ""), "kind": ekind, "id": ident,
                       "summary": summary, **extra})

    # ---- resolve the interesting-id set per target kind -------------------
    section_ids: set[str] = set()
    idea_ids: set[str] = set()
    adr_ids: set[str] = set()
    question_ids: set[str] = set()

    current: dict[str, Any] = {}

    if kind == "section":
        sec = spec.section_by_id(target)
        if sec is None:
            raise GreenhouseError(f"Unknown id: {target!r}")
        section_ids = {sec.id, *sec.aliases}
        current = {
            "section": sec.id,
            "maturity": sec.maturity,
            "workfile": sec.workfile,
            "open_questions": [q.model_dump(mode="json") for q in sec.open_questions],
            "assumptions": sec.assumptions,
            "text": _section_text(project, sec.workfile),
        }
    elif kind == "idea":
        idea = spec.idea_by_id(target)
        if idea is None:
            raise GreenhouseError(f"Unknown idea: {target!r}")
        idea_ids = {idea.id}
        add(idea.raised, "idea", idea.id,
            f"raised ({idea.source}): {idea.title}",
            status=idea.status, resolution=idea.resolution)
        current = idea.model_dump(mode="json")
    elif kind == "decision":
        adr_ids = {target}
        current = _decision_record(project, target) or {}
        if not current:
            raise GreenhouseError(f"Unknown ADR: {target!r}")
    elif kind == "question":
        question_ids = {target}
        found = spec.question_by_id(target)
        if found:
            sec, q = found
            add(q.raised, "question", q.id, f"open on {sec.id}: {q.text}", blocking=q.blocking)
            current = {"status": "open", "section": sec.id, "text": q.text}
        else:
            current = {"status": "resolved-or-unknown"}
    elif kind == "req":
        location = _find_req(project, target)
        if location is None:
            raise GreenhouseError(f"{target} not found in any workfile")
        current = location
        idea_ids = {i for i in location["why"] if i.startswith("idea-")}
        adr_ids = {i for i in location["why"] if re.fullmatch(r"\d{4}", i)}
        for idea_id in idea_ids:
            idea = spec.idea_by_id(idea_id)
            if idea:
                add(idea.raised, "idea", idea.id, f"cited idea: {idea.title}",
                    status=idea.status, resolution=idea.resolution)
        for rid in location["refs"]:
            add("", "citation", rid, f"cites external material {rid}")
    elif kind in ("source", "reference"):
        record = (_source_record(spec, target) if kind == "source"
                  else _reference_record(project, target))
        if record is None:
            raise GreenhouseError(f"Unknown {kind}: {target!r}")
        current = record
        add(record.get("added") or record.get("retrieved"), kind, target,
            f"registered: {record.get('title', '')}")
        for path, lineno in _citations_of(project, target):
            add("", "citation", f"{path}:{lineno}", f"cited from {path} line {lineno}")

    # ---- sweep history files ---------------------------------------------
    for path, fm in history.iter_history_frontmatter(project):
        ftype = fm.get("type", path.parent.name)
        fid = str(fm.get("id", path.stem))
        date = fm.get("date") or fm.get("retrieved")

        def listed(key: str, fm: dict[str, Any] = fm) -> set[str]:
            return {str(x) for x in fm.get(key) or []}

        hits = False
        if kind == "section":
            hits = bool(section_ids & (listed("sections") | listed("sections_touched")))
        elif kind == "idea":
            hits = bool(idea_ids & (listed("ideas") | listed("ideas_raised") | listed("ideas_resolved")))
        elif kind == "decision":
            hits = bool(adr_ids & (listed("decisions") | listed("supersedes"))) \
                or (ftype == "decision" and fid in adr_ids) \
                or str(fm.get("superseded_by") or "") in adr_ids
        elif kind == "question":
            hits = bool(question_ids & (listed("questions_asked") | listed("questions_resolved")))
        elif kind == "req":
            hits = bool(adr_ids & listed("decisions")) or (ftype == "decision" and fid in adr_ids)
        elif kind in ("source", "reference"):
            hits = ftype == "reference" and fid == target

        if not hits:
            continue

        if ftype == "session":
            _, body = mdutil.parse_frontmatter(path.read_text())
            transitions = [
                f"{t.get('section')}: {t.get('from')} → {t.get('to')}"
                for t in fm.get("maturity_transitions") or []
                if not section_ids or str(t.get("section")) in section_ids
            ]
            add(date, "session", fid,
                _session_summary(fm, section_ids, question_ids),
                transitions=transitions,
                commits=[str(c) for c in fm.get("commits") or []],
                body=body.strip())
        elif ftype == "decision":
            add(date, "decision", fid,
                f"{fm.get('title', '')} [{fm.get('status', '?')}]",
                supersedes=[str(s) for s in fm.get("supersedes") or []],
                superseded_by=fm.get("superseded_by"),
                ideas=[str(i) for i in fm.get("ideas") or []],
                body=mdutil.parse_frontmatter(path.read_text())[1].strip())
        elif ftype == "reference":
            add(date, "reference", fid, f"cached extraction: {fm.get('title', '')}",
                origin=fm.get("origin"))

    # ---- state-side records tied to a section target ----------------------
    if kind == "section":
        for idea in spec.ideas:
            if section_ids & set(idea.relates_to):
                summary = f"idea ({idea.status}): {idea.title}"
                if idea.status in ("rejected", "obsolete") and idea.resolution:
                    summary += f" — {idea.resolution}"
                add(idea.raised, "idea", idea.id, summary,
                    status=idea.status, resolution=idea.resolution)
        for src in spec.sources:
            if section_ids & set(src.relates_to):
                add(src.added, "source", src.id, f"source on file: {src.title}")
        sec = spec.section_by_id(target)
        for q in sec.open_questions:
            add(q.raised, "question", q.id,
                f"still open{' (blocking)' if q.blocking else ''}: {q.text}")

    events.sort(key=lambda e: (e["date"] or "9999", e["kind"], e["id"]))
    return {"target": target, "kind": kind, "current": current, "events": events}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(result: dict[str, Any], context: bool = False) -> str:
    """Human/agent-readable narrative; context=True includes session Q&A bodies
    and the current text — the bundle a re-evaluation drill starts from."""
    lines = [f"# Trace: {result['target']} ({result['kind']})", ""]
    cur = result["current"]
    if result["kind"] == "section" and cur:
        lines += [
            f"**Now:** maturity `{cur['maturity']}`, workfile `{cur.get('workfile') or '—'}`",
            "",
        ]
        if cur.get("open_questions"):
            lines.append("**Open questions:**")
            for q in cur["open_questions"]:
                flag = " *(blocking)*" if q.get("blocking") else ""
                lines.append(f"- {q['id']}{flag}: {q['text']}")
            lines.append("")
        if cur.get("assumptions"):
            lines.append("**Assumptions:** " + "; ".join(cur["assumptions"]))
            lines.append("")
    if not result["events"]:
        lines.append("_No recorded history yet._")
    else:
        lines.append("## Timeline")
        lines.append("")
        for e in result["events"]:
            date = e["date"] or "····-··-··"
            lines.append(f"- **{date}** `{e['kind']}` {e['id']} — {e['summary']}")
            for t in e.get("transitions") or []:
                lines.append(f"    - maturity {t}")
            if e.get("supersedes"):
                lines.append(f"    - supersedes: {', '.join(e['supersedes'])}")
            if e.get("superseded_by"):
                lines.append(f"    - superseded by: {e['superseded_by']}")
            if e.get("commits"):
                lines.append(f"    - commits: {', '.join(e['commits'])}")
            if context and e.get("body"):
                body = e["body"].strip()
                lines.append("")
                lines.append("  " + "\n  ".join(body.splitlines()))
                lines.append("")
    if context and result["kind"] == "section" and cur.get("text"):
        lines += ["", "## Current text", "", cur["text"].rstrip()]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _section_text(project: Project, workfile: str | None) -> str | None:
    if not workfile:
        return None
    path, _, anchor = workfile.partition("#")
    fpath = project.root / path
    if not fpath.exists():
        return None
    text = fpath.read_text()
    return mdutil.extract_section_slice(text, anchor) if anchor else text


def _session_summary(fm: dict, section_ids: set[str], question_ids: set[str]) -> str:
    bits = []
    touched = [str(s) for s in fm.get("sections_touched") or []]
    if touched:
        bits.append("touched " + ", ".join(touched))
    asked = [str(q) for q in fm.get("questions_asked") or []]
    resolved = [str(q) for q in fm.get("questions_resolved") or []]
    if question_ids:
        asked = [q for q in asked if q in question_ids]
        resolved = [q for q in resolved if q in question_ids]
    if asked:
        bits.append("asked " + ", ".join(asked))
    if resolved:
        bits.append("resolved " + ", ".join(resolved))
    return "; ".join(bits) or "session"


def _decision_record(project: Project, adr_id: str) -> dict[str, Any] | None:
    path = history.decision_path(project, adr_id)
    if path is None:
        return None
    fm, body = mdutil.parse_frontmatter(path.read_text())
    fm["body"] = body.strip()
    return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in fm.items()}


def _source_record(spec: Any, source_id: str) -> dict[str, Any] | None:
    src = spec.source_by_id(source_id)
    return src.model_dump(mode="json") if src else None


def _reference_record(project: Project, ref_id: str) -> dict[str, Any] | None:
    if project.references_dir.exists():
        for f in project.references_dir.glob(f"{ref_id}-*.md"):
            fm, body = mdutil.parse_frontmatter(f.read_text())
            fm["body"] = body.strip()
            fm["path"] = str(f.relative_to(project.root))
            return {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in fm.items()}
    return None


def _find_req(project: Project, req_id: str) -> dict[str, Any] | None:
    for wf in sorted(project.workfiles_dir.glob("*.md")):
        text = wf.read_text()
        for lineno, line in enumerate(text.splitlines()):
            if req_id in line:
                window = "\n".join(text.splitlines()[lineno:lineno + 2])
                why = [i for _, i in mdutil.extract_why_ids(window)]
                refs = [i for _, i in mdutil.extract_ref_ids(window)]
                return {
                    "file": str(wf.relative_to(project.root)),
                    "line": lineno + 1,
                    "text": line.strip(),
                    "why": why,
                    "refs": refs,
                }
    return None


def _citations_of(project: Project, ident: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    if project.workfiles_dir.exists():
        for wf in sorted(project.workfiles_dir.glob("*.md")):
            for lineno, line in enumerate(wf.read_text().splitlines()):
                if ident in line:
                    hits.append((str(wf.relative_to(project.root)), lineno + 1))
    return hits
