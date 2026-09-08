"""Trello dashboard plan: the desired board derived from spec state.

`plan()` returns plain data — lists in display order and one card per
greenhouse id (sections, open and answered questions, ideas, plus one status
card). `/spec-trello` reconciles this against the real board through the
Trello MCP tools; nothing here talks to the network, and nothing ever flows
back from Trello into spec-state.yaml (the board is a read-only mirror).

Card identity is the `[<id>]` prefix of the card name: ids are permanent in
greenhouse, so a renamed question or a section that changed maturity keeps
its card and simply moves.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from . import coverage as coverage_mod
from . import history as history_mod
from .models import MATURITY_ORDER

if TYPE_CHECKING:
    from .state import Project

# Trello limits (trelloWriteCard): name ≤ 512, desc ≤ 2048.
NAME_MAX = 200
DESC_MAX = 2000

LIST_STATUS = "Status"
LIST_BLOCKING = "Blocking questions"
LIST_OPEN = "Open questions"
LIST_ANSWERED = "Answered"
LIST_IDEAS_OPEN = "Ideas · open"
LIST_IDEAS_RESOLVED = "Ideas · resolved"


def section_list(maturity: str) -> str:
    return f"Sections · {maturity}"


LISTS: list[str] = [
    LIST_STATUS,
    LIST_BLOCKING,
    LIST_OPEN,
    LIST_ANSWERED,
    *(section_list(m) for m in MATURITY_ORDER),
    LIST_IDEAS_OPEN,
    LIST_IDEAS_RESOLVED,
]

# Where a card whose id is no longer in the plan belongs, by kind.
# `None` = archive it (a section that vanished from the taxonomy).
RETIRE_TO: dict[str, str | None] = {
    "question": LIST_ANSWERED,
    "idea": LIST_IDEAS_RESOLVED,
    "section": None,
    "status": None,
}

CARD_ID_RE = re.compile(r"^\[([A-Za-z0-9_.:-]+)\]")


def card_kind(card_id: str) -> str:
    """Kind inferred from the id shape — the same rule the skill applies to
    cards it finds on the board."""
    if card_id == "status":
        return "status"
    if card_id.startswith("q-"):
        return "question"
    if card_id.startswith("idea-"):
        return "idea"
    return "section"


def card_id_from_name(name: str) -> str | None:
    m = CARD_ID_RE.match(name.strip())
    return m.group(1) if m else None


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _desc(lines: list[str], project: str, card_id: str) -> str:
    body = "\n".join(line for line in lines if line is not None)
    footer = f"\n\n—\ngreenhouse: {project} / {card_id}"
    room = DESC_MAX - len(footer)
    if len(body) > room:
        body = body[: room - 1].rstrip() + "…"
    return body + footer


def _card(
    project: str,
    card_id: str,
    list_name: str,
    name: str,
    desc_lines: list[str],
    pos: int,
    labels: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    card = {
        "id": card_id,
        "kind": card_kind(card_id),
        "list": list_name,
        "name": _clip(f"[{card_id}] {name}", NAME_MAX),
        "desc": _desc(desc_lines, project, card_id),
        "pos": pos,
        "labels": labels or [],
    }
    card.update(extra)
    return card


def answered_questions(project: Project) -> dict[str, list[str]]:
    """Question ids that some session or ADR recorded as resolved (or asked
    and no longer open), mapped to the history ids that record them."""
    resolved: dict[str, list[str]] = {}
    for _, fm in history_mod.iter_history_frontmatter(project):
        hid = str(fm.get("id", ""))
        if not hid:
            continue
        for key in ("questions_resolved", "questions_asked"):
            for q in fm.get(key) or []:
                resolved.setdefault(str(q), [])
                if key == "questions_resolved" and hid not in resolved[str(q)]:
                    resolved[str(q)].append(hid)
    return resolved


def plan(project: Project) -> dict[str, Any]:
    from .state import today

    spec = project.spec()
    report = coverage_mod.compute(project)
    name = project.name
    cfg = spec.trello

    stale_by_section: dict[str, list[str]] = {}
    for item in report["stale"]:
        what = item.get("dependency") or item.get("source", "?")
        stale_by_section.setdefault(item["section"], []).append(f"{item['reason']} ({what})")
    blocker_rank = {b["question"]: i for i, b in enumerate(report["blockers"])}
    impact = {b["question"]: b["impact"] for b in report["blockers"]}

    cards: list[dict[str, Any]] = []
    counters: dict[str, int] = {}

    def next_pos(list_name: str) -> int:
        counters[list_name] = counters.get(list_name, 0) + 1
        return counters[list_name]

    # -- status card ----------------------------------------------------
    hist = report["histogram"]
    ladder = "  ".join(f"{m}: {hist.get(m, 0)}" for m in MATURITY_ORDER)
    status_lines = [
        f"**{spec.title or name}** — {spec.one_liner}".rstrip(" —"),
        f"Sections: {report['total_sections']} ({ladder})",
        f"Blocking questions: {len(report['blockers'])} · "
        f"open questions: {sum(len(s.open_questions) for s in spec.sections)} · "
        f"stale sections: {len({i['section'] for i in report['stale']})} · "
        f"open ideas: {report['ideas']['open']}",
        "",
    ]
    if report["suggestions"]:
        status_lines.append("**Next targets (greenhouse coverage):**")
        for s in report["suggestions"][:5]:
            status_lines.append(f"- {s['action']} {s['section'] or 'ideas'} — {s['reason']}")
        status_lines.append("")
    status_lines.append(f"Last synced from spec-state: {today().isoformat()} (updated {spec.updated})")
    cards.append(
        _card(
            name, "status", LIST_STATUS,
            f"{spec.title or name} — {hist.get('agreed', 0) + hist.get('locked', 0)}/"
            f"{report['total_sections']} agreed",
            status_lines, next_pos(LIST_STATUS),
        )
    )

    # -- questions --------------------------------------------------------
    open_q: list[tuple[Any, Any]] = [(s, q) for s in spec.sections for q in s.open_questions]
    open_q.sort(
        key=lambda sq: (
            not sq[1].blocking,
            blocker_rank.get(sq[1].id, 10**6),
            spec.sections.index(sq[0]),
            sq[1].id,
        )
    )
    for sec, q in open_q:
        list_name = LIST_BLOCKING if q.blocking else LIST_OPEN
        gates = spec.dependents_of(sec.id)
        lines = [
            q.text,
            "",
            f"Section: {sec.id} ({sec.title}, {sec.maturity})",
            f"Blocking: {'yes — gates ' + str(impact.get(q.id, len(gates))) + ' dependent section(s)' if q.blocking else 'no'}",
            f"Raised: {q.raised or '—'}",
            f"Gates: {', '.join(gates)}" if q.blocking and gates else None,
        ]
        cards.append(
            _card(
                name, q.id, list_name,
                ("⛔ " if q.blocking else "") + q.text,
                lines, next_pos(list_name),
                labels=["blocking"] if q.blocking else [],
            )
        )

    open_ids = {q.id for _, q in open_q}
    for qid, resolvers in sorted(answered_questions(project).items()):
        if qid in open_ids:
            continue
        by = ", ".join(resolvers) if resolvers else "a session log (see greenhouse trace)"
        cards.append(
            _card(
                name, qid, LIST_ANSWERED,
                f"answered — see {by}",
                [f"Resolved; recorded in: {by}.", f"Reasoning: `greenhouse trace {qid}`."],
                next_pos(LIST_ANSWERED),
                preserve_name=True,
            )
        )

    # -- sections ---------------------------------------------------------
    for sec in spec.sections:
        list_name = section_list(sec.maturity)
        stale = stale_by_section.get(sec.id, [])
        n_block = sum(1 for q in sec.open_questions if q.blocking)
        tags = []
        if stale:
            tags.append("⚠ stale")
        if n_block:
            tags.append(f"⛔ {n_block} blocking")
        elif sec.open_questions:
            tags.append(f"{len(sec.open_questions)} open")
        title = sec.title + (" · " + " · ".join(tags) if tags else "")
        lines = [
            f"Maturity: {sec.maturity}" + (f" (agreed {sec.agreed_at})" if sec.agreed_at else ""),
            f"Workfile: {sec.workfile}" if sec.workfile else None,
            f"Depends on: {', '.join(sec.depends_on) or '—'}",
            f"Dependents: {', '.join(spec.dependents_of(sec.id, transitive=False)) or '—'}",
            f"Last touched: {sec.last_touched or '—'}",
        ]
        if stale:
            lines += ["", "**Stale:** " + "; ".join(stale)]
        if sec.open_questions:
            lines += ["", "**Open questions:**"]
            lines += [
                f"- {q.id}{' ⛔' if q.blocking else ''}: {_clip(q.text, 160)}"
                for q in sec.open_questions
            ]
        if sec.decisions:
            lines += ["", f"Decisions: {', '.join(sec.decisions)}"]
        if sec.ideas:
            lines.append(f"Ideas: {', '.join(sec.ideas)}")
        if sec.assumptions:
            lines += ["", f"**Assumptions ({len(sec.assumptions)}):**"]
            lines += [f"- {_clip(a, 160)}" for a in sec.assumptions]
        labels = ["section"] + (["stale"] if stale else []) + (["blocking"] if n_block else [])
        cards.append(_card(name, sec.id, list_name, title, lines, next_pos(list_name), labels))

    # -- ideas ------------------------------------------------------------
    for idea in spec.ideas:
        active = idea.status in ("open", "deferred")
        list_name = LIST_IDEAS_OPEN if active else LIST_IDEAS_RESOLVED
        suffix = "" if idea.status == "open" else f" · {idea.status}"
        if idea.resolution and idea.status == "accepted":
            suffix += f" ({idea.resolution})"
        lines = [
            f"Status: {idea.status}",
            f"Relates to: {', '.join(idea.relates_to) or '—'}",
            f"Source: {idea.source} · raised {idea.raised or '—'}",
            f"Resolution: {idea.resolution}" if idea.resolution else None,
            f"Backlog entry: {idea.ref}" if idea.ref else None,
        ]
        labels = ["idea"] + (["deferred"] if idea.status == "deferred" else [])
        cards.append(
            _card(name, idea.id, list_name, idea.title + suffix, lines, next_pos(list_name), labels)
        )

    return {
        "project": name,
        "title": spec.title or name,
        "enabled": bool(cfg and cfg.enabled),
        "board": cfg.board if cfg else None,
        "board_url": cfg.board_url if cfg else None,
        "generated": today().isoformat(),
        "lists": list(LISTS),
        "retire_to": dict(RETIRE_TO),
        "cards": cards,
    }
