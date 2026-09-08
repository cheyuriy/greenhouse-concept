"""Gap detection and next-target ranking: blanks, blockers by
downstream impact, stale-agreed sections, assumption inventory, suggestions.

`compute()` returns plain data — the CLI renders it for humans, `--json` is the
machine interface `/spec-continue` consumes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import deliverables as deliverables_mod

if TYPE_CHECKING:
    from .state import Project


def compute(project: Project) -> dict[str, Any]:
    spec = project.spec()

    histogram: dict[str, int] = {}
    for s in spec.sections:
        histogram[s.maturity] = histogram.get(s.maturity, 0) + 1

    # -- blanks -------------------------------------------------------------
    blanks = [
        {"section": s.id, "title": s.title, "maturity": s.maturity}
        for s in spec.sections
        if s.maturity in ("none", "stub")
    ]

    # -- blockers: blocking questions ranked by what they gate --------------
    blockers: list[dict[str, Any]] = []
    for s in spec.sections:
        dependents = spec.dependents_of(s.id)
        for q in s.open_questions:
            if q.blocking:
                blockers.append(
                    {
                        "question": q.id,
                        "section": s.id,
                        "text": q.text,
                        "unblocks": dependents,
                        "impact": len(dependents),
                    }
                )
    blockers.sort(key=lambda b: (-b["impact"], b["section"]))

    # -- staleness: agreed sections whose dependencies moved afterwards -----
    stale: list[dict[str, Any]] = []
    for s in spec.sections:
        if s.maturity not in ("agreed", "locked") or not s.agreed_at:
            continue
        for dep_id in s.depends_on:
            dep = spec.section_by_id(dep_id)
            if dep and dep.last_touched and dep.last_touched > s.agreed_at:
                stale.append(
                    {
                        "section": s.id,
                        "reason": "dependency-changed",
                        "dependency": dep.id,
                        "dependency_touched": str(dep.last_touched),
                        "agreed_at": str(s.agreed_at),
                    }
                )

    # source drift also reuses the staleness machinery
    try:
        from . import sources as sources_mod

        for item in sources_mod.drifted_citations(project, spec):
            stale.append(item)
    except ImportError:  # pragma: no cover - sources module lands in phase 4
        pass

    # -- assumptions inventory ---------------------------------------------
    assumptions = [
        {"section": s.id, "text": a} for s in spec.sections for a in s.assumptions
    ]

    # -- idea backlog summary ----------------------------------------------
    try:
        from . import ideas as ideas_mod

        idea_findings = ideas_mod.audit(project, spec)
    except ImportError:  # pragma: no cover
        idea_findings = []
    open_ideas = [i for i in spec.ideas if i.status in ("open", "deferred")]
    ideas_summary = {
        "open": len(open_ideas),
        "flagged": len({f["idea"] for f in idea_findings}),
    }

    # -- deliverables: readiness + files whose inputs moved after the build --
    deliverable_rows = deliverables_mod.readiness(project, spec)
    feeds: dict[str, list[str]] = {}
    for d in spec.deliverables:
        for sid in d.sections:
            feeds.setdefault(spec.canonical_section_id(sid) or sid, []).append(d.id)

    def _feeds(section_id: str) -> str:
        ids = feeds.get(section_id)
        return f"; feeds {', '.join(ids)}" if ids else ""

    # -- ranked suggestions -------------------------------------------------
    suggestions: list[dict[str, Any]] = []
    stale_ids = {item["section"] for item in stale}
    for sid in sorted(stale_ids):
        reasons = [i["reason"] for i in stale if i["section"] == sid]
        suggestions.append(
            {
                "action": "re-review",
                "section": sid,
                "reason": f"agreed but stale ({', '.join(sorted(set(reasons)))})",
                "score": 90,
            }
        )
    for b in blockers:
        suggestions.append(
            {
                "action": "answer",
                "section": b["section"],
                "reason": f"blocking question {b['question']} gates {b['impact']} section(s): {b['text']}",
                "score": 70 + min(b["impact"] * 2, 18),
            }
        )
    for blank in blanks:
        already = any(x["section"] == blank["section"] for x in suggestions)
        if already:
            continue
        impact = len(spec.dependents_of(blank["section"]))
        suggestions.append(
            {
                "action": "fill",
                "section": blank["section"],
                "reason": (
                    f"{blank['maturity']} — unblocks {impact} dependent section(s)"
                    if impact
                    else f"{blank['maturity']} — no prose yet"
                ) + _feeds(blank["section"]),
                "score": 50 + min(impact * 3, 19),
            }
        )
    for s in spec.sections:
        if s.maturity == "draft" and not any(x["section"] == s.id for x in suggestions):
            n_open = len(s.open_questions)
            suggestions.append(
                {
                    "action": "deepen",
                    "section": s.id,
                    "reason": f"draft with {n_open} open question(s)" + _feeds(s.id),
                    "score": 40 + min(n_open * 2, 9),
                }
            )
    for row in deliverable_rows:
        if row["exists"] and row["stale"]:
            suggestions.append(
                {
                    "action": "rebuild",
                    "section": None,
                    "deliverable": row["id"],
                    "reason": f"deliverable built {row['built_at']} but "
                    f"{', '.join(row['stale'])} changed since",
                    "score": 60,
                }
            )
    if ideas_summary["flagged"]:
        suggestions.append(
            {
                "action": "triage-ideas",
                "section": None,
                "reason": f"{ideas_summary['open']} open idea(s), {ideas_summary['flagged']} flagged by audit",
                "score": 45,
            }
        )
    suggestions.sort(key=lambda x: -x["score"])

    return {
        "project": project.name,
        "histogram": histogram,
        "total_sections": len(spec.sections),
        "blanks": blanks,
        "blockers": blockers,
        "stale": stale,
        "assumptions": assumptions,
        "ideas": ideas_summary,
        "deliverables": deliverable_rows,
        "suggestions": suggestions,
    }
