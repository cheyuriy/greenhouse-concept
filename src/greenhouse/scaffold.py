"""Project scaffolding: folders + spec-state.yaml seeded from an archetype taxonomy."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import mdutil
from .models import GreenhouseError
from .state import Project, today
from .workspace import Workspace, as_workspace, tooling_root

_yaml = YAML(typ="rt")
_yaml.default_flow_style = False


def _templates_dir(workspace: Workspace | Path) -> Path:
    """The workspace's own templates/ when it has one, else the tooling checkout's."""
    ws = as_workspace(workspace)
    if ws.templates_dir:
        return ws.templates_dir
    fallback = tooling_root() / "templates"
    if fallback.exists():
        return fallback
    raise GreenhouseError(f"No templates/ directory found (looked in {ws.root} and {fallback})")


def load_taxonomy(workspace: Workspace | Path, archetype: str) -> dict:
    path = _templates_dir(workspace) / "taxonomies" / f"{archetype}.yaml"
    if not path.exists():
        available = sorted(
            p.stem for p in (_templates_dir(workspace) / "taxonomies").glob("*.yaml")
        )
        raise GreenhouseError(
            f"Unknown archetype {archetype!r}. Available: {', '.join(available) or '(none)'}"
        )
    return dict(_yaml.load(path.read_text()))


def load_guidance(workspace: Workspace | Path, archetype: str) -> dict[str, str]:
    """Optional per-section drafting guidance (templates/docs/<archetype>.yaml)."""
    path = _templates_dir(workspace) / "docs" / f"{archetype}.yaml"
    if not path.exists():
        return {}
    data = _yaml.load(path.read_text()) or {}
    return {str(k): str(v).strip() for k, v in (data.get("sections") or {}).items()}


def create_project(
    workspace: Workspace | Path,
    name: str,
    archetype: str = "cli-tool",
    title: str = "",
    one_liner: str = "",
    audience: list[str] | None = None,
    date: dt.date | None = None,
) -> Project:
    """Create <workspace.projects_dir>/<name>/ per the §2 folder contract, every
    section `none`. A bare path is taken as a workspace root (legacy: projects
    under its `projects/`). Discovery is glob-based, so projects located
    elsewhere inside the workspace keep working."""
    date = date or today()
    ws = as_workspace(workspace)
    taxonomy = load_taxonomy(ws, archetype)
    guidance = load_guidance(ws, archetype)
    root = ws.projects_dir / name
    if (root / "spec-state.yaml").exists():
        raise GreenhouseError(f"Project {name!r} already exists at {root}")

    # -- folders ------------------------------------------------------------
    for sub in (
        "workfiles",
        "sources",
        "history/decisions",
        "history/sessions",
        "history/references",
        "final",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)

    # -- workfile skeletons (headings must exist so anchors validate) -------
    workfile_meta = {w["path"]: w for w in taxonomy.get("workfiles", [])}
    by_file: dict[str, list[dict]] = {}
    for sec in taxonomy["sections"]:
        if sec.get("workfile"):
            by_file.setdefault(sec["workfile"], []).append(sec)

    for path, secs in by_file.items():
        meta = workfile_meta.get(path, {})
        lines = [
            f"# {meta.get('title', path)}",
            "",
            f"<!-- Workfile for {name}. WIP prose lives here; final/ is generated. -->",
            "",
        ]
        for sec in secs:
            heading = sec.get("heading", sec["title"])
            lines += [f"## {heading}", ""]
            hint = guidance.get(sec["id"])
            if hint:
                lines += [f"<!-- guidance: {hint} -->", ""]
            lines += ["_Not yet drafted._", ""]
        (root / "workfiles" / path).write_text("\n".join(lines))

    (root / "workfiles" / "IDEAS.md").write_text(
        "# Idea backlog\n\n"
        "<!-- One section per idea, indexed in spec-state.yaml. Maintained via\n"
        "     `greenhouse idea ...` so prose and index cannot drift. -->\n"
    )
    (root / "sources" / "INDEX.md").write_text(
        f"# Sources — {name}\n\n_No sources registered yet. Add with `greenhouse source add`._\n"
    )
    (root / "history" / "INDEX.md").write_text(
        f"# History — {name}\n\n_No sessions or decisions recorded yet._\n"
    )
    (root / "final" / ".gitkeep").write_text("")

    # -- spec-state.yaml ----------------------------------------------------
    state = CommentedMap()
    state["project"] = name
    state["title"] = title or name
    state["archetype"] = archetype
    state["created"] = date
    state["updated"] = date
    state["audience"] = list(audience or [])
    state["one_liner"] = one_liner
    sections = CommentedSeq()
    for sec in taxonomy["sections"]:
        entry = CommentedMap()
        entry["id"] = sec["id"]
        entry["title"] = sec["title"]
        entry["maturity"] = "none"
        if sec.get("workfile"):
            heading = sec.get("heading", sec["title"])
            entry["workfile"] = f"workfiles/{sec['workfile']}#{mdutil.slugify(heading)}"
        else:
            entry["workfile"] = None
        entry["depends_on"] = list(sec.get("depends_on", []))
        entry["open_questions"] = CommentedSeq()
        entry["last_touched"] = None
        sections.append(entry)
    state["sections"] = sections
    state["ideas"] = CommentedSeq()
    state["sources"] = CommentedSeq()
    # deliverables: the archetype's expectation of what finalization hands
    # over; copied (not referenced) so /spec-new can re-verify per project
    deliverables = CommentedSeq()
    section_ids = {sec["id"] for sec in taxonomy["sections"]}
    for d in taxonomy.get("deliverables") or []:
        unknown = [sid for sid in d.get("sections", []) if sid not in section_ids]
        if unknown:
            raise GreenhouseError(
                f"archetype {archetype!r}: deliverable {d.get('id')!r} names unknown "
                f"section(s) {', '.join(unknown)}"
            )
        entry = CommentedMap()
        entry["id"] = d["id"]
        entry["title"] = d.get("title", d["id"])
        entry["format"] = d.get("format", "markdown")
        entry["path"] = d.get("path") or f"{d['id']}.md"
        entry["description"] = " ".join(str(d.get("description", "")).split())
        entry["sections"] = CommentedSeq(list(d.get("sections", [])))
        entry["built_at"] = None
        deliverables.append(entry)
    state["deliverables"] = deliverables

    with (root / "spec-state.yaml").open("w") as fh:
        _yaml.dump(state, fh)

    return Project(root, workspace=ws)
