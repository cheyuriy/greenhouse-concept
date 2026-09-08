"""Workfile lint: REQ-id discipline, RFC-2119 usage,
acceptance criteria, provenance, TODO/ASSUMPTION inventory, accepted-but-
uncited ADRs, confidential verbatim runs. Errors gate finalize; the rest is
inventory for the drill loop."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from . import history, mdutil, sources
from .models import GreenhouseError

if TYPE_CHECKING:
    from .state import Project

BOLD_REQ_RE = mdutil.BOLD_REQ_RE
BAD_REQ_RE = re.compile(r"\*\*(REQ-[^*\s]+)\*\*")
_ACCEPT_WINDOW = 4  # minimum lines after a REQ scanned for an acceptance criterion
# (the scan extends to the end of the REQ's paragraph when that is longer)


def finding(level: str, file: str, line: int, rule: str, message: str) -> dict[str, Any]:
    return {"level": level, "file": file, "line": line, "rule": rule, "message": message}


def lint_project(
    project: Project, pending_decisions: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """`pending_decisions`: ADR ids treated as resolvable for this run only."""
    findings: list[dict[str, Any]] = []
    if not project.workfiles_dir.exists():
        raise GreenhouseError("No workfiles/ directory")

    spec = project.spec()
    known = history.known_ids(project, spec, pending_decisions)
    req_defined: dict[str, tuple[str, int]] = {}

    for wf in sorted(project.workfiles_dir.glob("*.md")):
        rel = f"workfiles/{wf.name}"
        text = wf.read_text()
        lines = text.splitlines()

        # heading structure
        headings = mdutil.parse_headings(text)
        if not headings or headings[0]["level"] != 1:
            findings.append(finding("info", rel, 1, "heading-structure",
                                    "file should start with a single H1"))
        for prev, cur in itertools.pairwise(headings):
            if cur["level"] > prev["level"] + 1:
                findings.append(finding("info", rel, cur["line"] + 1, "heading-structure",
                                        f"heading level jumps {prev['level']}→{cur['level']}"))

        for lineno, line in enumerate(lines, start=1):
            # REQ ids: format + uniqueness
            for m in BAD_REQ_RE.finditer(line):
                if not BOLD_REQ_RE.match(m.group(0)):
                    findings.append(finding("error", rel, lineno, "req-id-format",
                                            f"{m.group(1)} must match REQ-<SECTION>-<NNN>"))
            for m in BOLD_REQ_RE.finditer(line):
                rid = m.group(1)
                if rid in req_defined:
                    f0, l0 = req_defined[rid]
                    findings.append(finding("error", rel, lineno, "req-id-duplicate",
                                            f"{rid} already defined at {f0}:{l0}"))
                else:
                    req_defined[rid] = (rel, lineno)
                para_end = lineno - 1
                while para_end < len(lines) and lines[para_end].strip():
                    para_end += 1
                window = "\n".join(
                    lines[lineno - 1:max(para_end, lineno - 1 + _ACCEPT_WINDOW)]
                )
                # acceptance criterion or explicit gap marker
                if "[needs-criterion]" not in window and not re.search(
                    r"Acceptance:", window, re.IGNORECASE
                ):
                    findings.append(finding("warning", rel, lineno, "needs-criterion",
                                            f"{rid} has no acceptance criterion "
                                            "(add `Acceptance:` or mark `[needs-criterion]`)"))
                # provenance discipline (see CLAUDE.md)
                has_why = bool(mdutil.WHY_MARKER_RE.search(window))
                has_ref = bool(mdutil.REF_MARKER_RE.search(window))
                if not has_why and not has_ref:
                    findings.append(finding("warning", rel, lineno, "req-no-provenance",
                                            f"{rid} carries no why/ref marker"))
                elif has_ref and not has_why:
                    findings.append(finding("warning", rel, lineno, "source-only-justification",
                                            f"{rid} leans only on source material — restate it "
                                            "on its own terms via a decision before promoting"))

            # RFC-2119 discipline: bare lowercase modal outside a REQ line
            if not BOLD_REQ_RE.search(line) and not line.lstrip().startswith(("#", "<!--", ">")):
                if re.search(r"\b(should|must)\b", line) and not re.search(r"\b(SHOULD|MUST)\b", line):
                    findings.append(finding("info", rel, lineno, "rfc2119",
                                            "bare 'should/must' outside a requirement — "
                                            "use MUST/SHOULD/MAY deliberately or rephrase"))

            # TODO / assumption inventory
            if re.search(r"\b(TODO|TBD|FIXME)\b|\?\?\?", line):
                findings.append(finding("info", rel, lineno, "todo", line.strip()[:100]))
            if "**ASSUMPTION:**" in line:
                findings.append(finding("info", rel, lineno, "assumption", line.strip()[:100]))

        # dangling marker ids (validate also catches these; lint is one-stop)
        for lineno0, wid in mdutil.extract_why_ids(text):
            kind = "idea" if wid.startswith("idea-") else "decision"
            if wid not in known[kind]:
                findings.append(finding("error", rel, lineno0 + 1, "dangling-why",
                                        f"why-marker cites unknown {kind} {wid}"))
        for lineno0, rid in mdutil.extract_ref_ids(text):
            kind = "source" if rid.startswith("src-") else "reference"
            if rid not in known[kind]:
                findings.append(finding("error", rel, lineno0 + 1, "dangling-ref",
                                        f"ref-marker cites unknown {kind} {rid}"))

    # accepted ADRs that nothing cites (a decision nothing implements)
    cited_adrs: set[str] = set()
    for wf in sorted(project.workfiles_dir.glob("*.md")):
        for _, wid in mdutil.extract_why_ids(wf.read_text()):
            if re.fullmatch(r"\d{4}", wid):
                cited_adrs.add(wid)
    for path, fm in history.iter_history_frontmatter(project):
        if fm.get("type") == "decision" and fm.get("status") == "accepted":
            adr_id = str(fm.get("id"))
            if adr_id not in cited_adrs:
                findings.append(finding("warning", str(path.relative_to(project.root)), 1,
                                        "adr-uncited",
                                        f"accepted ADR {adr_id} is cited by no workfile"))

    # confidential verbatim runs
    for leak in sources.confidential_leaks(project):
        findings.append(finding("error", leak["file"], 1, "confidential-verbatim",
                                leak["detail"]))

    order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (order[f["level"]], f["file"], f["line"]))
    return findings


def has_errors(findings: list[dict[str, Any]]) -> bool:
    return any(f["level"] == "error" for f in findings)
