"""Cross-document checks: dangling markdown links and anchors
inside the project (workfiles and history), and REQ ids mentioned in
workfile prose but never defined."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from . import history, mdutil

if TYPE_CHECKING:
    from .state import Project

MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def xref_project(project: Project) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    defined_reqs = history.req_ids(project)

    scan_dirs = [project.workfiles_dir, project.history_dir]
    for base in scan_dirs:
        if not base.exists():
            continue
        for md in sorted(base.rglob("*.md")):
            rel = str(md.relative_to(project.root))
            text = md.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                for m in MD_LINK_RE.finditer(line):
                    target = m.group(2)
                    if re.match(r"[a-z]+://|mailto:", target):
                        continue  # external URL — not ours to verify offline
                    path_part, _, anchor = target.partition("#")
                    if path_part:
                        resolved = (md.parent / path_part).resolve()
                        try:
                            resolved.relative_to(project.root)
                        except ValueError:
                            problems.append(
                                {"file": rel, "line": lineno, "kind": "outside-project",
                                 "detail": f"link {target!r} points outside the project"}
                            )
                            continue
                        if not resolved.exists():
                            problems.append(
                                {"file": rel, "line": lineno, "kind": "dangling-link",
                                 "detail": f"link target {target!r} does not exist"}
                            )
                            continue
                        if anchor and resolved.suffix == ".md":
                            if anchor not in mdutil.anchors_in(resolved.read_text()):
                                problems.append(
                                    {"file": rel, "line": lineno, "kind": "dangling-anchor",
                                     "detail": f"anchor #{anchor} not found in {path_part}"}
                                )
                    elif anchor:  # same-document anchor
                        if anchor not in mdutil.anchors_in(text):
                            problems.append(
                                {"file": rel, "line": lineno, "kind": "dangling-anchor",
                                 "detail": f"anchor #{anchor} not found in this file"}
                            )
                # REQ ids referenced (non-bold mention) but never defined.
                # Workfiles only: history records options that were never
                # taken ("a new REQ-X-005 ..."), so an undefined id there is
                # a faithful record, not a dangling reference.
                if base != project.workfiles_dir:
                    continue
                for m in mdutil.REQ_ID_RE.finditer(line):
                    rid = m.group(0)
                    if rid not in defined_reqs:
                        problems.append(
                            {"file": rel, "line": lineno, "kind": "undefined-req",
                             "detail": f"{rid} referenced but defined nowhere"}
                        )
    return problems
