"""Local MCP server: exposes the greenhouse state machine to any
MCP client. Registered in .mcp.json as `uv run greenhouse-mcp` (stdio)."""

from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

from . import coverage as coverage_mod
from . import state as state_mod
from . import trace as trace_mod
from .integrations import Document, get_exporter
from .models import GreenhouseError
from .workspace import find_workspace

mcp = FastMCP(
    "greenhouse",
    instructions=(
        "Spec-growing workspace tools: discover projects, read coverage/gaps, "
        "list open questions, reconstruct reasoning history, export documents."
    ),
)


def _project(name: str | None = None) -> state_mod.Project:
    return state_mod.resolve_project(name, cwd=Path.cwd())


@mcp.tool
def list_projects() -> str:
    """List spec projects in this workspace with maturity summary."""
    ws = find_workspace(Path.cwd())
    out: list[dict] = [{"workspace": str(ws.root), "resolved_from": ws.source}]
    for root in state_mod.discover_projects(ws):
        p = state_mod.Project(root, workspace=ws)
        spec = p.spec()
        histogram: dict[str, int] = {}
        for s in spec.sections:
            histogram[s.maturity] = histogram.get(s.maturity, 0) + 1
        out.append(
            {
                "project": p.name,
                "title": spec.title,
                "one_liner": spec.one_liner,
                "sections": len(spec.sections),
                "maturity": histogram,
                "updated": str(spec.updated or ""),
            }
        )
    return json.dumps(out, indent=2)


@mcp.tool
def coverage(project: str | None = None) -> str:
    """Gap report for a project: blanks, blockers, stale sections, suggestions.
    Omit `project` to resolve from the working directory."""
    return json.dumps(coverage_mod.compute(_project(project)), indent=2, default=str)


@mcp.tool
def open_questions(project: str | None = None) -> str:
    """All open questions, blocking first."""
    spec = _project(project).spec()
    questions = [
        {
            "id": q.id,
            "section": s.id,
            "text": q.text,
            "blocking": q.blocking,
            "raised": str(q.raised or ""),
        }
        for s in spec.sections
        for q in s.open_questions
    ]
    questions.sort(key=lambda q: (not q["blocking"], q["id"]))
    return json.dumps(questions, indent=2)


@mcp.tool
def trace(target: str, project: str | None = None) -> str:
    """Reconstruct the reasoning history behind any id (section, idea-NNNN,
    q-…, ADR NNNN, src-/ref-NNNN, REQ-…)."""
    return json.dumps(trace_mod.trace(_project(project), target), indent=2, default=str)


@mcp.tool
def export_document(path: str, exporter: str = "noop", project: str | None = None) -> str:
    """Push a project document (e.g. final/SPEC.md) through a configured
    exporter. Only 'noop' ships today; see integrations/README.md."""
    p = _project(project)
    fpath = p.root / path
    if not fpath.exists():
        raise GreenhouseError(f"No such document: {path}")
    exp = get_exporter(exporter, p.workspace)
    doc = Document(title=fpath.stem, path=path, content=fpath.read_text())
    result = exp.push_document(p.name, doc)
    return json.dumps(
        {"ok": result.ok, "detail": result.detail, "remote_ref": result.remote_ref}
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
