"""The `greenhouse` CLI (typer). Every command resolves its project from CWD
per the rule in CLAUDE.md; `--project` overrides; ambiguity is a hard error listing
candidates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import bundle as bundle_mod
from . import coverage as coverage_mod
from . import dashboard as dashboard_mod
from . import deliverables as deliverables_mod
from . import gitutil, mdutil, scaffold
from . import history as history_mod
from . import ideas as ideas_mod
from . import lint as lint_mod
from . import references as references_mod
from . import sections as sections_mod
from . import sources as sources_mod
from . import state as state_mod
from . import trace as trace_mod
from . import xref as xref_mod
from .models import (
    AmbiguousProjectError,
    GreenhouseError,
    ProjectNotFoundError,
    ValidationFailure,
)
from .state import Project, resolve_project
from .workspace import (
    Workspace,
    find_workspace,
    init_workspace,
    local_config_path,
    write_local_config,
)

app = typer.Typer(no_args_is_help=True, help=__doc__)
state_app = typer.Typer(no_args_is_help=True, help="Safe mutations of spec-state.yaml.")
app.add_typer(state_app, name="state")
idea_app = typer.Typer(no_args_is_help=True, help="Idea backlog: add, triage, audit.")
app.add_typer(idea_app, name="idea")
session_app = typer.Typer(no_args_is_help=True, help="Session logs (id-linked history).")
app.add_typer(session_app, name="session")
decision_app = typer.Typer(no_args_is_help=True, help="Decision records (ADRs).")
app.add_typer(decision_app, name="decision")
source_app = typer.Typer(no_args_is_help=True, help="Curated input material (sources/).")
app.add_typer(source_app, name="source")
ref_app = typer.Typer(no_args_is_help=True, help="Extraction cache (history/references/).")
app.add_typer(ref_app, name="ref")
section_app = typer.Typer(
    no_args_is_help=True, help="One section's prose slice: show, write, guidance, deps."
)
app.add_typer(section_app, name="section")
trello_app = typer.Typer(
    no_args_is_help=True,
    help="Read-only Trello dashboard: configure the board, print the desired board state.",
)
app.add_typer(trello_app, name="trello")
deliverable_app = typer.Typer(
    no_args_is_help=True,
    help="Deliverables: the artefacts finalization hands over beyond SPEC.md.",
)
app.add_typer(deliverable_app, name="deliverable")
workspace_app = typer.Typer(
    no_args_is_help=True,
    help="Where projects live: show/init/use a workspace, set a default project.",
)
app.add_typer(workspace_app, name="workspace")

PROJECT_OPT = typer.Option(
    None, "--project", "-p",
    help="Project name (also accepted before the subcommand).",
)

console = Console()
err_console = Console(stderr=True)


@app.callback()
def _main(
    ctx: typer.Context,
    project: str | None = typer.Option(
        None, "--project", "-p",
        help="Project name; default: CWD (inside the workspace) → local default → sole project.",
    ),
) -> None:
    ctx.obj = {"project": project}


def get_project(ctx: typer.Context, explicit: str | None = None) -> Project:
    try:
        return resolve_project(explicit or (ctx.obj.get("project") if ctx.obj else None))
    except AmbiguousProjectError as exc:
        err_console.print(
            "[red]Ambiguous project.[/red] Pass --project with one of: "
            + ", ".join(exc.candidates)
        )
        raise typer.Exit(2) from exc
    except ProjectNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc


def fail(message: str, code: int = 1) -> None:
    err_console.print(f"[red]{message}[/red]")
    raise typer.Exit(code)


# ---------------------------------------------------------------------------
# new / projects / validate
# ---------------------------------------------------------------------------


@app.command()
def new(
    name: str = typer.Argument(..., help="Project folder name, e.g. bq-assist"),
    archetype: str = typer.Option("cli-tool", help="Taxonomy archetype."),
    title: str = typer.Option("", help="Human title of the project."),
    one_liner: str = typer.Option("", "--one-liner", help="One-sentence description."),
    audience: list[str] = typer.Option([], "--audience", help="Repeatable audience entry."),
) -> None:
    """Scaffold a new project in the workspace, every section at maturity `none`."""
    try:
        ws = find_workspace(Path.cwd())
        project = scaffold.create_project(
            ws, name, archetype=archetype, title=title,
            one_liner=one_liner, audience=audience,
        )
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Created project [bold]{project.name}[/bold] at {project.root}")
    spec = project.spec()
    console.print(f"{len(spec.sections)} sections seeded from {archetype!r}, all `none`.")
    if spec.deliverables:
        console.print(
            f"{len(spec.deliverables)} deliverable(s) expected at finalization: "
            + ", ".join(d.id for d in spec.deliverables)
            + " — re-verify with `greenhouse deliverable list`."
        )
    else:
        console.print(
            "No deliverables declared by this archetype — add them with "
            "`greenhouse deliverable add` if finalization must hand over more than SPEC.md."
        )


@app.command()
def projects() -> None:
    """List discovered projects with maturity summary and last-updated date."""
    try:
        ws = find_workspace(Path.cwd())
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Workspace: {ws.describe()}")
    roots = state_mod.discover_projects(ws)
    if not roots:
        console.print("No projects. Create one with: greenhouse new <name>")
        return
    table = Table("project", "sections", "maturity", "updated", "path")
    for root in roots:
        p = Project(root, workspace=ws)
        spec = p.spec()
        counts: dict[str, int] = {}
        for s in spec.sections:
            counts[s.maturity] = counts.get(s.maturity, 0) + 1
        summary = "  ".join(
            f"{m}:{counts[m]}" for m in ("none", "stub", "draft", "agreed", "locked") if m in counts
        )
        name = f"{p.name} *" if p.name == ws.default_project else p.name
        table.add_row(
            name, str(len(spec.sections)), summary, str(spec.updated or "—"),
            _rel(root, ws.root),
        )
    console.print(table)
    if ws.default_project:
        console.print("* default project (greenhouse.local.toml)")


def _rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix() or "."
    except ValueError:
        return str(path)


@app.command()
def validate(ctx: typer.Context) -> None:
    """Schema + id-graph validation (workfiles, anchors, history links, markers)."""
    project = get_project(ctx)
    try:
        state_mod.validate_project(project)
    except ValidationFailure as exc:
        for problem in exc.problems:
            err_console.print(f"[red]✗[/red] {problem}")
        raise typer.Exit(1) from exc
    console.print(f"[green]✓[/green] {project.name}: state is valid")


@app.command()
def root(
    ctx: typer.Context,
    project_dir: bool = typer.Option(
        False, "--project-dir",
        help="Print the resolved project's directory relative to its git root instead.",
    ),
    absolute: bool = typer.Option(
        False, "--absolute", help="With --project-dir: print the absolute path."
    ),
    workspace: bool = typer.Option(
        False, "--workspace", help="Print the workspace root instead of a git root."
    ),
) -> None:
    """Print the git root of the resolved project (absolute) — the repo its
    spec lives in, which is the workspace repo, not this checkout. Skills run
    every git call as `git -C "$(uv run greenhouse root)"` so the working
    directory never matters. Without a resolvable project, the workspace root."""
    if workspace:
        print(find_workspace(Path.cwd()).root)
        return
    if project_dir:
        project = get_project(ctx)
        print(project.root if absolute else project.root.relative_to(project.repo_root).as_posix())
        return
    try:
        print(resolve_project(ctx.obj.get("project") if ctx.obj else None).repo_root)
    except (AmbiguousProjectError, ProjectNotFoundError):
        print(find_workspace(Path.cwd()).root)


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------


def _print_workspace(ws: Workspace) -> None:
    table = Table(show_header=False, box=None)
    table.add_row("workspace", str(ws.root))
    table.add_row("resolved from", ws.source)
    table.add_row("marker", str(ws.marker) if ws.marker.exists() else "(none — legacy layout)")
    table.add_row("projects dir", str(ws.projects_dir))
    table.add_row("templates", str(ws.templates_dir or "(tooling defaults)"))
    table.add_row("local config", str(ws.local_path or "(none)"))
    table.add_row("default project", ws.default_project or "(none)")
    console.print(table)


@workspace_app.command("show")
def workspace_show(ctx: typer.Context) -> None:
    """Resolved workspace, its config, and which project a command would act on."""
    try:
        ws = find_workspace(Path.cwd())
    except GreenhouseError as exc:
        fail(str(exc))
    _print_workspace(ws)
    explicit = ctx.obj.get("project") if ctx.obj else None
    try:
        project = resolve_project(explicit, workspace=ws)
    except AmbiguousProjectError as exc:
        console.print(
            "project: [yellow]ambiguous[/yellow] — " + ", ".join(exc.candidates)
            + " (pass --project or `workspace project <name>`)"
        )
        raise typer.Exit(2) from exc
    except ProjectNotFoundError as exc:
        console.print(f"project: [red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"project: [bold]{project.name}[/bold] (resolved by {project.resolved_by})")
    console.print(f"git root: {project.repo_root}")


@workspace_app.command("init")
def workspace_init(
    path: Path = typer.Argument(..., help="Folder to mark as a workspace (created if missing)."),
    projects_dir: str = typer.Option(
        ".", "--projects-dir", help="Where `greenhouse new` scaffolds, relative to the folder."
    ),
    use: bool = typer.Option(
        False, "--use", help="Also point this checkout at it (writes greenhouse.local.toml)."
    ),
) -> None:
    """Mark a folder as a workspace (greenhouse.toml). Git is never run here:
    init/commit the folder yourself if it is to be its own repo."""
    try:
        ws = init_workspace(path, projects_dir=projects_dir)
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Workspace marked at [bold]{ws.root}[/bold] ({ws.marker.name} written)")
    if use:
        cfg = local_config_path(Path.cwd())
        write_local_config(cfg, workspace=str(ws.root))
        console.print(f"{cfg} → workspace = {ws.root}")
    if not (ws.root / ".git").exists():
        console.print(f"Not a git repo yet: `git -C {ws.root} init` when ready.")


@workspace_app.command("use")
def workspace_use(
    path: Path | None = typer.Argument(
        None, help="Workspace folder. Omit with --clear to fall back to the checkout."
    ),
    project: str | None = typer.Option(
        None, "--project", "-p", help="Also set the default project."
    ),
    clear: bool = typer.Option(False, "--clear", help="Forget the configured workspace."),
) -> None:
    """Point this checkout at a workspace: writes `workspace = ...` to the
    git-ignored greenhouse.local.toml (GREENHOUSE_WORKSPACE overrides it)."""
    cfg = local_config_path(Path.cwd())
    if clear:
        write_local_config(cfg, workspace=None, project=None)
        console.print(f"{cfg}: workspace and default project cleared")
        return
    if path is None:
        fail("Pass a workspace folder, or --clear.")
    root = path.expanduser().resolve()
    if not root.is_dir():
        fail(f"{root} is not a directory (create it with `greenhouse workspace init {root}`)")
    updates: dict = {"workspace": str(root)}
    if project:
        updates["project"] = project
    else:
        updates["project"] = None  # a default from another workspace is meaningless here
    write_local_config(cfg, **updates)
    console.print(f"{cfg} → workspace = {root}" + (f", project = {project}" if project else ""))
    if not (root / "greenhouse.toml").exists():
        console.print(
            "[yellow]warning:[/yellow] no greenhouse.toml there — "
            f"`greenhouse workspace init {root}` marks it (projects_dir defaults to '.')."
        )


@workspace_app.command("project")
def workspace_project(
    name: str | None = typer.Argument(None, help="Project to use when none is named."),
    clear: bool = typer.Option(False, "--clear", help="Forget the default project."),
) -> None:
    """Set the default project for this checkout (greenhouse.local.toml).
    Sits below --project and the CWD walk-up, above the sole-project rule."""
    cfg = local_config_path(Path.cwd())
    if clear:
        write_local_config(cfg, project=None)
        console.print(f"{cfg}: default project cleared")
        return
    if not name:
        fail("Pass a project name, or --clear.")
    try:
        project = resolve_project(name)  # must exist in the resolved workspace
    except (AmbiguousProjectError, ProjectNotFoundError, GreenhouseError) as exc:
        fail(str(exc))
    write_local_config(cfg, project=project.name)
    console.print(f"{cfg} → project = {project.name} ({project.root})")


@app.command()
def check(
    ctx: typer.Context,
    project_name: str | None = PROJECT_OPT,
    with_xref: bool = typer.Option(False, "--xref", help="Also run xref."),
    show_all: bool = typer.Option(False, "--all", help="Show info-level lint findings too."),
    pending_adr: list[str] = typer.Option(
        [], "--pending-adr",
        help="ADR id a draft may cite before `decision new` writes it (repeatable).",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """validate + lint (+ xref) in one run, warn/error lines only. Exit 1 on any error."""
    project = get_project(ctx, project_name)
    problems: list[str] = []
    try:
        state_mod.validate_project(project, pending_decisions=pending_adr)
    except ValidationFailure as exc:
        problems = list(exc.problems)
    try:
        findings = lint_mod.lint_project(project, pending_decisions=pending_adr)
    except GreenhouseError as exc:
        fail(str(exc))
    xref_problems = xref_mod.xref_project(project) if with_xref else []
    shown = [f for f in findings if show_all or f["level"] != "info"]
    infos = len(findings) - len([f for f in findings if f["level"] != "info"])
    if as_json:
        print(json.dumps({"validate": problems, "lint": findings, "xref": xref_problems},
                         indent=2))
    else:
        for problem in problems:
            err_console.print(f"[red]✗ validate[/red] {problem}")
        for f in shown:
            style = {"error": "red", "warning": "yellow", "info": "dim"}[f["level"]]
            console.print(
                f"[{style}]{f['level']:<7}[/{style}] {f['file']}:{f['line']} "
                f"[{f['rule']}] {f['message']}"
            )
        for x in xref_problems:
            console.print(f"[red]✗ xref[/red] {x['file']}:{x['line']} [{x['kind']}] {x['detail']}")
        n_err = len(problems) + sum(1 for f in findings if f["level"] == "error") + len(xref_problems)
        n_warn = sum(1 for f in findings if f["level"] == "warning")
        verdict = "[red]✗[/red]" if n_err else "[green]✓[/green]"
        console.print(
            f"{verdict} {project.name}: {n_err} error(s), {n_warn} warning(s), "
            f"{infos} info (hidden unless --all)"
            + (f"; pending ADR {', '.join(pending_adr)}" if pending_adr else "")
        )
    if problems or lint_mod.has_errors(findings) or xref_problems:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# state show|set|question|questions|resolve|link|assume|retract
# ---------------------------------------------------------------------------


@state_app.command("show")
def state_show(
    ctx: typer.Context,
    section_id: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """All sections, or full detail of one."""
    project = get_project(ctx)
    spec = project.spec()
    if section_id:
        sec = spec.section_by_id(section_id)
        if not sec:
            fail(f"Unknown section: {section_id}")
        detail = sec.model_dump(mode="json")
        detail["dependents"] = spec.dependents_of(sec.id, transitive=False)
        detail["transitive_dependents"] = spec.dependents_of(sec.id)
        console.print_json(json.dumps(detail, indent=2)) if as_json \
            else console.print(detail)
        return
    if as_json:
        console.print_json(json.dumps(spec.model_dump(mode="json"), default=str))
        return
    table = Table("id", "maturity", "questions", "last touched")
    for s in spec.sections:
        blocking = sum(1 for q in s.open_questions if q.blocking)
        qcol = f"{len(s.open_questions)}" + (f" ({blocking} blocking)" if blocking else "")
        table.add_row(s.id, s.maturity, qcol, str(s.last_touched or "—"))
    console.print(table)


@state_app.command("set")
def state_set(
    ctx: typer.Context,
    section_ids: list[str] = typer.Argument(..., help="One or more section ids."),
    maturity: str = typer.Option(..., "--maturity", "-m"),
    force: bool = typer.Option(False, "--force", help="Override the blocking-question check."),
) -> None:
    """Set one or more sections' maturity (refused for agreed/locked while
    blocking questions remain; nothing is saved if any section is refused)."""
    if maturity not in ("none", "stub", "draft", "agreed", "locked"):
        fail(f"Invalid maturity {maturity!r}")
    project = get_project(ctx)
    try:
        for sid in section_ids:
            project.set_maturity(sid, maturity, force=force)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    for sid in section_ids:
        console.print(f"{sid} → [bold]{maturity}[/bold]")


@state_app.command("questions")
def state_questions(
    ctx: typer.Context,
    section_id: str | None = typer.Argument(None, help="Limit to one section."),
    blocking: bool = typer.Option(False, "--blocking", help="Blocking questions only."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Open questions across the project (or one section), blocking first."""
    project = get_project(ctx)
    spec = project.spec()
    if section_id and not spec.section_by_id(section_id):
        fail(f"Unknown section: {section_id}")
    rows = [
        {"id": q.id, "section": s.id, "text": q.text, "blocking": q.blocking,
         "raised": str(q.raised or "")}
        for s in spec.sections
        for q in s.open_questions
        if (not section_id or spec.section_by_id(section_id).id == s.id)
        and (not blocking or q.blocking)
    ]
    rows.sort(key=lambda q: (not q["blocking"], q["id"]))
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print("No open questions")
        return
    for q in rows:
        flag = " [red](blocking)[/red]" if q["blocking"] else ""
        console.print(f"[bold]{q['id']}[/bold] on {q['section']}{flag}: {q['text']}")


@state_app.command("question")
def state_question(
    ctx: typer.Context,
    section_id: str,
    text: str,
    blocking: bool = typer.Option(False, "--blocking"),
) -> None:
    """Record an open question against a section."""
    project = get_project(ctx)
    try:
        qid = project.add_question(section_id, text, blocking=blocking)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    console.print(f"Added [bold]{qid}[/bold] to {section_id}" + (" (blocking)" if blocking else ""))


@state_app.command("resolve")
def state_resolve(ctx: typer.Context, question_id: str) -> None:
    """Mark a question resolved (it moves to the session log's record)."""
    project = get_project(ctx)
    try:
        section_id, text = project.resolve_question(question_id)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    console.print(f"Resolved {question_id} on {section_id}: {text}")


@state_app.command("link")
def state_link(
    ctx: typer.Context,
    section_ids: list[str] = typer.Argument(..., help="Sections to link."),
    decision: str | None = typer.Option(None, help="ADR id, e.g. 0003"),
    session: str | None = typer.Option(None, help="Session id, e.g. 2026-08-26-auth"),
    idea: str | None = typer.Option(None, help="Idea id, e.g. idea-0007"),
) -> None:
    """Add decision/session/idea back-links to sections."""
    if not (decision or session or idea):
        fail("Nothing to link: pass --decision, --session, and/or --idea")
    project = get_project(ctx)
    try:
        if decision:
            project.link_decision(section_ids, decision)
        if session:
            project.link_session(section_ids, session)
        if idea:
            for sid in section_ids:
                project.link_idea_to_section(sid, idea)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    console.print(f"Linked {', '.join(section_ids)}")


@state_app.command("depend")
def state_depend(
    ctx: typer.Context,
    section_id: str,
    on: list[str] = typer.Option(..., "--on", help="Section id this section depends on (repeatable)."),
) -> None:
    """Add depends_on edges (DAG enforced). Edges are load-bearing: they drive
    blocker ranking and staleness, so add them when prose relies on a section."""
    project = get_project(ctx)
    added: list[str] = []
    try:
        for dep in on:
            if project.add_dependency(section_id, dep):
                added.append(dep)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    if added:
        console.print(f"{section_id} now depends on: {', '.join(added)}")
    else:
        console.print(f"{section_id}: no new edges (all already present)")


@state_app.command("assume")
def state_assume(ctx: typer.Context, section_id: str, text: str) -> None:
    """Record an explicit assumption against a section."""
    project = get_project(ctx)
    try:
        project.add_assumption(section_id, text)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    console.print(f"Assumption recorded on {section_id}")


@state_app.command("retract")
def state_retract(
    ctx: typer.Context,
    section_id: str,
    match: str = typer.Argument(
        ..., help="1-based index, exact text, or a unique substring of the assumption."
    ),
) -> None:
    """Retract an assumption once it is verified or superseded (record why in the ADR)."""
    project = get_project(ctx)
    try:
        text = project.retract_assumption(section_id, match)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    console.print(f"Retracted assumption on {section_id}: {text}")


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


@app.command()
def coverage(
    ctx: typer.Context,
    project_name: str | None = PROJECT_OPT,
    top: int = typer.Option(8, "--top", help="How many suggested targets to list."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Gaps, blockers, stale sections, assumptions, and suggested next targets."""
    project = get_project(ctx, project_name)
    report = coverage_mod.compute(project)
    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return

    console.print(f"[bold]{report['project']}[/bold] — {report['total_sections']} sections")
    console.print(
        "  "
        + "  ".join(
            f"{m}: {report['histogram'].get(m, 0)}"
            for m in ("none", "stub", "draft", "agreed", "locked")
        )
    )
    if report["stale"]:
        console.print("\n[yellow]Stale (agreed, but inputs moved):[/yellow]")
        for item in report["stale"]:
            what = item.get("dependency") or item.get("source", "?")
            console.print(f"  • {item['section']} — {item['reason']} ({what})")
    if report["blockers"]:
        console.print("\n[red]Blocking questions (by downstream impact):[/red]")
        for b in report["blockers"]:
            console.print(f"  • {b['question']} on {b['section']} (gates {b['impact']}): {b['text']}")
    if report["assumptions"]:
        console.print(f"\nAssumptions on record: {len(report['assumptions'])}")
    if report["ideas"]["open"]:
        console.print(
            f"Ideas: {report['ideas']['open']} open, {report['ideas']['flagged']} flagged by audit"
        )
    if report["deliverables"]:
        console.print("\n[bold]Deliverables (expected at finalization):[/bold]")
        for d in report["deliverables"]:
            console.print(f"  • {_deliverable_status_line(d)}")
    if report["suggestions"]:
        console.print("\n[bold]Suggested next targets:[/bold]")
        for s in report["suggestions"][:top]:
            target = s.get("deliverable") or s["section"] or "ideas"
            console.print(f"  {s['score']:>3}  {s['action']:<12} {target:<20} {s['reason']}")


def _deliverable_status_line(d: dict) -> str:
    """One line per deliverable, shared by coverage, bundle and `deliverable list`."""
    if d["exists"]:
        state = (
            f"[yellow]stale[/yellow] (built {d['built_at']}; changed since: "
            f"{', '.join(d['stale'])})"
            if d["stale"]
            else f"[green]built[/green] {d['built_at']}"
        )
    elif d["ready"]:
        state = "[green]ready to write[/green]"
    elif not d["sections"]:
        state = "[red]no feeding sections[/red]"
    else:
        state = f"[dim]waiting on[/dim] {', '.join(d['missing'])}"
    return f"{d['id']} ({d['format']}) — {state}"


# ---------------------------------------------------------------------------
# trello configure|show|plan   (the /spec-trello skill does the MCP calls)
# ---------------------------------------------------------------------------


@trello_app.command("configure")
def trello_configure(
    ctx: typer.Context,
    board: str | None = typer.Option(None, "--board", help="Exact board name in Trello."),
    enable: bool | None = typer.Option(
        None, "--enable/--disable", help="Whether /spec-trello should mirror this project."
    ),
    url: str | None = typer.Option(
        None, "--url", help="Board URL, recorded after the first sync (pass '' to clear)."
    ),
) -> None:
    """Create or update the `trello:` block in spec-state.yaml (the only way to edit it)."""
    if board is None and enable is None and url is None:
        fail("Nothing to configure: pass --board, --enable/--disable, and/or --url")
    project = get_project(ctx)
    try:
        node = project.configure_trello(board=board, enabled=enable, board_url=url)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    state = "enabled" if node.get("enabled") else "disabled"
    console.print(
        f"Trello dashboard {state}: board [bold]{node.get('board') or '(unnamed)'}[/bold]"
        + (f" — {node.get('board_url')}" if node.get("board_url") else "")
    )


@trello_app.command("show")
def trello_show(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """The project's Trello configuration. Exit 3 when none is recorded."""
    project = get_project(ctx)
    cfg = project.spec().trello
    if as_json:
        print(json.dumps(cfg.model_dump(mode="json") if cfg else None, indent=2))
    elif cfg is None:
        console.print("No Trello dashboard configured (greenhouse trello configure --board …)")
    else:
        state = "enabled" if cfg.enabled else "disabled"
        console.print(f"Trello dashboard {state}: board [bold]{cfg.board}[/bold]"
                      + (f" — {cfg.board_url}" if cfg.board_url else ""))
    if cfg is None:
        raise typer.Exit(3)


@trello_app.command("plan")
def trello_plan(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Machine-readable (what /spec-trello consumes)."),
) -> None:
    """The desired board derived from spec state: lists in order and one card per
    section, question (open and answered), idea, plus a status card. Pure read."""
    project = get_project(ctx)
    report = dashboard_mod.plan(project)
    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return
    state = "enabled" if report["enabled"] else "disabled"
    console.print(f"[bold]{report['board'] or '(no board configured)'}[/bold] ({state})")
    for list_name in report["lists"]:
        cards = [c for c in report["cards"] if c["list"] == list_name]
        console.print(f"\n[bold]{list_name}[/bold] ({len(cards)})")
        for c in cards:
            console.print(f"  {c['name']}", markup=False)  # names start with [id]


# ---------------------------------------------------------------------------
# idea list|add|show|status|audit|sync
# ---------------------------------------------------------------------------


@idea_app.command("add")
def idea_add(
    ctx: typer.Context,
    title: str,
    body: str = typer.Option("", help="Elaboration prose for IDEAS.md."),
    relates: list[str] = typer.Option([], "--relates", help="Repeatable section id."),
    source: str = typer.Option("user", help="idea-scout | spec-critic | user | drill"),
    allow_duplicate: bool = typer.Option(
        False, "--allow-duplicate", help="Add despite a near-duplicate (cite why)."
    ),
) -> None:
    """Register an idea; near-duplicates of any status are refused with the original's fate."""
    project = get_project(ctx)
    try:
        idea_id = ideas_mod.add_idea(
            project, title, body=body, relates_to=relates, source=source,
            allow_duplicate=allow_duplicate,
        )
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Added [bold]{idea_id}[/bold]: {title}")


@idea_app.command("list")
def idea_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, help="Filter by status."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """The backlog, optionally filtered by status."""
    project = get_project(ctx)
    ideas = project.spec().ideas
    if status:
        ideas = [i for i in ideas if i.status == status]
    if as_json:
        print(json.dumps([i.model_dump(mode="json") for i in ideas], indent=2, default=str))
        return
    table = Table("id", "status", "title", "relates to", "raised")
    for i in ideas:
        table.add_row(i.id, i.status, i.title, ", ".join(i.relates_to) or "—", str(i.raised or "—"))
    console.print(table)


@idea_app.command("show")
def idea_show(ctx: typer.Context, idea_id: str) -> None:
    """One idea: index entry plus its IDEAS.md prose."""
    project = get_project(ctx)
    idea = project.spec().idea_by_id(idea_id)
    if not idea:
        fail(f"Unknown idea: {idea_id}")
    console.print(idea.model_dump(mode="json"))
    block = ideas_mod._idea_block(project.ideas_file.read_text(), idea_id)
    if block:
        console.print("\n" + block.strip())


@idea_app.command("status")
def idea_status(
    ctx: typer.Context,
    idea_id: str,
    status: str,
    resolution: str | None = typer.Option(
        None, help="ADR id for accepted; reason for rejected/obsolete/superseded."
    ),
) -> None:
    """Move an idea through its lifecycle (accepted requires an ADR id)."""
    project = get_project(ctx)
    try:
        ideas_mod.set_status(project, idea_id, status, resolution=resolution)
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"{idea_id} → [bold]{status}[/bold]")


@idea_app.command("audit")
def idea_audit(
    ctx: typer.Context,
    project_name: str | None = PROJECT_OPT,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Mechanical relevance flags (stale, orphaned, locked-target, aging) + sync check."""
    project = get_project(ctx, project_name)
    findings = ideas_mod.audit(project)
    sync = ideas_mod.sync_problems(project)
    if as_json:
        print(json.dumps({"findings": findings, "sync_problems": sync}, indent=2))
        return
    if not findings and not sync:
        console.print("[green]✓[/green] backlog is clean and in sync")
        return
    for f in findings:
        console.print(f"[yellow]•[/yellow] {f['idea']} [{f['kind']}] {f['detail']}")
    for p in sync:
        console.print(f"[red]✗ sync:[/red] {p}")
    if sync:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# trace / session / decision
# ---------------------------------------------------------------------------


@app.command()
def trace(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Section, idea-NNNN, q-…, ADR NNNN, src-/ref-NNNN, or REQ-… id."),
    project_name: str | None = PROJECT_OPT,
    as_json: bool = typer.Option(False, "--json"),
    context: bool = typer.Option(
        False, "--context", help="Full bundle: session Q&A bodies + current text."
    ),
) -> None:
    """Reconstruct the complete reasoning history behind any id."""
    project = get_project(ctx, project_name)
    try:
        result = trace_mod.trace(project, target)
    except GreenhouseError as exc:
        fail(str(exc))
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(trace_mod.render_markdown(result, context=context))


def _read_body(body: str, body_file: Path | None) -> str:
    """`--body-file -` reads stdin, so a heredoc needs no scratch file."""
    if body_file is not None and str(body_file) == "-":
        return sys.stdin.read()
    if body_file:
        return Path(body_file).read_text()
    return body


@session_app.command("log")
def session_log(
    ctx: typer.Context,
    slug: str = typer.Option(..., help="Short slug; id becomes YYYY-MM-DD-<slug>."),
    body: str = typer.Option("", help="Markdown body: the questions and answers verbatim."),
    body_file: Path | None = typer.Option(None, help="Read the body from a file instead."),
    touched: list[str] = typer.Option([], "--touched", help="Repeatable section id."),
    transition: list[str] = typer.Option(
        [], "--transition", help="section:from:to, repeatable."
    ),
    asked: list[str] = typer.Option([], "--asked", help="Question ids asked."),
    resolved: list[str] = typer.Option([], "--resolved", help="Question ids resolved."),
    idea_raised: list[str] = typer.Option([], "--idea-raised"),
    idea_resolved: list[str] = typer.Option([], "--idea-resolved"),
    decision: list[str] = typer.Option([], "--decision", help="ADR ids from this session."),
) -> None:
    """Append a session log with full frontmatter links; back-links applied,
    history/INDEX.md regenerated."""
    project = get_project(ctx)
    transitions = []
    for t in transition:
        parts = t.split(":")
        if len(parts) != 3:
            fail(f"--transition must be section:from:to, got {t!r}")
        transitions.append({"section": parts[0], "from": parts[1], "to": parts[2]})
    try:
        session_id = history_mod.write_session(
            project, slug, _read_body(body, body_file),
            sections_touched=touched, maturity_transitions=transitions,
            questions_asked=asked, questions_resolved=resolved,
            ideas_raised=idea_raised, ideas_resolved=idea_resolved,
            decisions=decision,
        )
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Logged session [bold]{session_id}[/bold]")


@session_app.command("commit")
def session_commit(
    ctx: typer.Context,
    session_id: str,
    rev: str = typer.Argument("HEAD", help="Commit sha or any git revision (default HEAD)."),
) -> None:
    """Record the git commit hash on a session (and its ADRs) after committing.
    Prints the subject of the follow-up commit that carries the recorded sha."""
    project = get_project(ctx)
    try:
        sha = gitutil.rev_parse(project.repo_root, rev)
        history_mod.record_commit(project, session_id, sha)
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"{session_id} ← commit {sha}")
    console.print("Follow-up commit subject (tree is dirty again):")
    print(history_mod.attach_commit_subject(project, session_id))


@session_app.command("commit-message")
def session_commit_message(
    ctx: typer.Context,
    session_id: str,
    subject: str | None = typer.Option(
        None, "--subject", help="What was settled; default: the session body's first line."
    ),
    trailer: list[str] = typer.Option(
        [], "--trailer", help="Extra 'Key: value' trailer line (repeatable)."
    ),
) -> None:
    """Print the spec commit message for a session — subject plus Sections /
    Ideas / Decisions / Session trailers from its frontmatter. Pipe into
    `git commit -F -`; the commit itself stays in the skill."""
    project = get_project(ctx)
    try:
        print(history_mod.commit_message(project, session_id, subject, trailer), end="")
    except GreenhouseError as exc:
        fail(str(exc))


@session_app.command("list")
def session_list(
    ctx: typer.Context,
    limit: int = typer.Option(5, "-n", "--limit", help="Newest N sessions (0 = all)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Recent sessions, newest first: id, sections touched, ADRs, commit."""
    project = get_project(ctx)
    rows = history_mod.list_sessions(project)
    if limit:
        rows = rows[:limit]
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print("No sessions logged")
        return
    table = Table("session", "sections", "decisions", "commit")
    for r in rows:
        table.add_row(r["id"], ", ".join(r["sections"]), ", ".join(r["decisions"]),
                      r["commits"][-1][:8] if r["commits"] else "—")
    console.print(table)


@session_app.command("show")
def session_show(ctx: typer.Context, session_id: str) -> None:
    """One session log: frontmatter and the verbatim Q&A body."""
    project = get_project(ctx)
    try:
        fm, body = history_mod.read_session(project, session_id)
    except GreenhouseError as exc:
        fail(str(exc))
    print(mdutil.dump_frontmatter(fm, body), end="")


@decision_app.command("new")
def decision_new(
    ctx: typer.Context,
    title: str = typer.Option(..., help="Decision title."),
    section: list[str] = typer.Option(..., "--section", help="Repeatable section id."),
    body: str = typer.Option("", help="Context, options considered, choice, consequences."),
    body_file: Path | None = typer.Option(None),
    idea: list[str] = typer.Option([], "--idea", help="Ideas weighed (incl. rejected)."),
    resolves: list[str] = typer.Option([], "--resolves", help="Question ids resolved."),
    supersedes: list[str] = typer.Option([], "--supersedes", help="Older ADR ids."),
    session: str | None = typer.Option(None, help="Session id this came from."),
    status: str = typer.Option("accepted"),
) -> None:
    """Write an ADR with complete frontmatter links; superseded ADRs are marked."""
    project = get_project(ctx)
    try:
        adr_id = history_mod.write_decision(
            project, title, _read_body(body, body_file), sections=section,
            ideas=idea, questions_resolved=resolves, supersedes=supersedes,
            session=session, status=status,
        )
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Recorded ADR [bold]{adr_id}[/bold]: {title}")


@decision_app.command("next-id")
def decision_next_id(ctx: typer.Context) -> None:
    """The id `decision new` will assign next — cite it in the draft's why-markers
    and pass it to `check --pending-adr` until the ADR is written."""
    print(get_project(ctx).next_adr_id())


@decision_app.command("list")
def decision_list(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """All ADRs in id order: id, date, status, title, sections."""
    project = get_project(ctx)
    rows = history_mod.list_decisions(project)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print("No decisions recorded")
        return
    table = Table("adr", "date", "status", "sections", "title")
    for r in rows:
        table.add_row(r["id"], r["date"], r["status"], ", ".join(r["sections"]), r["title"])
    console.print(table)


@decision_app.command("show")
def decision_show(ctx: typer.Context, adr_id: str) -> None:
    """One ADR: frontmatter and body."""
    project = get_project(ctx)
    try:
        fm, body = history_mod.read_decision(project, adr_id)
    except GreenhouseError as exc:
        fail(str(exc))
    print(mdutil.dump_frontmatter(fm, body), end="")


# ---------------------------------------------------------------------------
# section show|write|guidance|deps
# ---------------------------------------------------------------------------


@section_app.command("show")
def section_show(ctx: typer.Context, section_id: str) -> None:
    """Print the section's slice: its heading through the line before the next
    heading of the same or higher level, located by the anchor in spec-state."""
    project = get_project(ctx)
    try:
        print(sections_mod.show(project, section_id), end="")
    except GreenhouseError as exc:
        fail(str(exc))


@section_app.command("guidance")
def section_guidance(ctx: typer.Context, section_id: str) -> None:
    """Print the drafting guidance comment under the section's heading."""
    project = get_project(ctx)
    try:
        text = sections_mod.guidance(project, section_id)
        feeds = deliverables_mod.for_section(project.spec(), section_id)
    except GreenhouseError as exc:
        fail(str(exc))
    print(text or "(no guidance comment)")
    if feeds:
        print()
        print("Feeds deliverables (carry what each needs; the section is not limited to them):")
        for d in feeds:
            print(f"  - {d['id']} — {d['title']} ({d['format']}): {d['description']}")


@section_app.command("deps")
def section_deps(
    ctx: typer.Context,
    section_id: str,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Upstream chain and dependents (direct and transitive) with maturity."""
    project = get_project(ctx)
    try:
        info = sections_mod.deps(project, section_id)
    except GreenhouseError as exc:
        fail(str(exc))
    if as_json:
        print(json.dumps(info, indent=2))
        return
    console.print(f"[bold]{info['section']}[/bold] ({info['maturity']})")
    for key, label in (("depends_on", "depends on"), ("upstream", "upstream (transitive)"),
                       ("dependents", "dependents"),
                       ("transitive_dependents", "dependents (transitive)")):
        rows = info[key]
        rendered = ", ".join(f"{r['section']} ({r['maturity']})" for r in rows) or "—"
        console.print(f"  {label}: {rendered}")
    feeds = ", ".join(f"{d['id']} ({d['format']})" for d in info["deliverables"]) or "—"
    console.print(f"  feeds deliverables: {feeds}")


@section_app.command("write")
def section_write(
    ctx: typer.Context,
    section_id: str,
    from_file: Path = typer.Option(
        ..., "--from-file", help="New slice text, heading included; '-' reads stdin."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the diff, change nothing."),
) -> None:
    """Replace the section's slice with the given text. The first heading must
    be the section's own; the guidance comment is kept if the text dropped it."""
    project = get_project(ctx)
    new_text = sys.stdin.read() if str(from_file) == "-" else Path(from_file).read_text()
    try:
        diff = sections_mod.write(project, section_id, new_text, dry_run=dry_run)
    except GreenhouseError as exc:
        fail(str(exc))
    print(diff, end="")
    if not diff:
        console.print("(no change)")
    elif dry_run:
        console.print("[dim](dry run — nothing written)[/dim]")


# ---------------------------------------------------------------------------
# source add|list|show|check|orphans
# ---------------------------------------------------------------------------


@source_app.command("add")
def source_add(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File path (copied into sources/) or URL."),
    title: str = typer.Option(..., help="What this material is."),
    kind: str | None = typer.Option(None, help="file | url | note | transcript (auto)."),
    relates: list[str] = typer.Option([], "--relates", help="Repeatable section id."),
    confidential: bool = typer.Option(False, "--confidential",
                                      help="Forbid verbatim quoting beyond a short run."),
    note: str | None = typer.Option(None, help="Why it matters."),
) -> None:
    """Register input material (indexed, checksummed, citable via <!-- ref: src-NNNN -->)."""
    project = get_project(ctx)
    try:
        src_id = sources_mod.add_source(
            project, target, title=title, kind=kind, relates_to=relates,
            confidential=confidential, note=note,
        )
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Registered [bold]{src_id}[/bold]: {title}")


@source_app.command("list")
def source_list(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """All registered sources."""
    project = get_project(ctx)
    srcs = project.spec().sources
    if as_json:
        print(json.dumps([s.model_dump(mode="json") for s in srcs], indent=2, default=str))
        return
    table = Table("id", "kind", "title", "where", "flags")
    for s in srcs:
        table.add_row(s.id, s.kind, s.title, s.path or s.url or "—",
                      "confidential" if s.confidential else "")
    console.print(table)


@source_app.command("show")
def source_show(ctx: typer.Context, source_id: str) -> None:
    """One source's index entry."""
    project = get_project(ctx)
    src = project.spec().source_by_id(source_id)
    if not src:
        fail(f"Unknown source: {source_id}")
    console.print(src.model_dump(mode="json"))


@source_app.command("check")
def source_check(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Re-hash files; report drift (citing agreed sections go stale in coverage)."""
    project = get_project(ctx)
    findings = sources_mod.check(project)
    if as_json:
        print(json.dumps(findings, indent=2))
        return
    if not findings:
        console.print("[green]✓[/green] all sources unchanged")
        return
    for f in findings:
        style = "yellow" if f["kind"] == "unchecked-url" else "red"
        console.print(f"[{style}]•[/{style}] {f['source']} [{f['kind']}] {f['detail']}")


@source_app.command("orphans")
def source_orphans(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Sources nothing cites, and citations pointing at missing sources."""
    project = get_project(ctx)
    report = sources_mod.orphans(project)
    if as_json:
        print(json.dumps(report, indent=2))
        return
    for sid in report["uncited"]:
        console.print(f"[yellow]•[/yellow] {sid} is registered but never cited")
    for d in report["dangling"]:
        console.print(f"[red]✗[/red] {d['file']}:{d['line']} cites unknown {d['id']}")
    if not report["uncited"] and not report["dangling"]:
        console.print("[green]✓[/green] no orphans")


# ---------------------------------------------------------------------------
# ref add|lookup|list|show|check|promote
# ---------------------------------------------------------------------------


@ref_app.command("add")
def ref_add(
    ctx: typer.Context,
    origin: str = typer.Argument(..., help="URL or file path the extraction came from."),
    title: str = typer.Option(...),
    body: str = typer.Option("", help="The extraction (include a 'Not extracted' list)."),
    body_file: Path | None = typer.Option(None),
    freshness: str = typer.Option("volatile", help="volatile (expires) | stable (never)."),
    expires_days: int = typer.Option(references_mod.DEFAULT_EXPIRES_DAYS, "--expires-days"),
    section: list[str] = typer.Option([], "--section", help="Repeatable related section id."),
    session: str | None = typer.Option(None, help="Session id it was retrieved in."),
) -> None:
    """Cache an extraction so this origin is never re-read from scratch."""
    project = get_project(ctx)
    try:
        ref_id = references_mod.add_reference(
            project, origin, title=title, body=_read_body(body, body_file),
            freshness=freshness, expires_after_days=expires_days,
            sections=section, retrieved_in=session,
        )
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"Cached [bold]{ref_id}[/bold]: {title}")


@ref_app.command("lookup")
def ref_lookup(
    ctx: typer.Context,
    origin: str = typer.Argument(..., help="URL or file path about to be fetched/read."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run BEFORE any fetch. Exit 0 = fresh hit (use it, skip the fetch);
    exit 3 = stale hit (refetch, then update); exit 4 = miss (fetch + ref add)."""
    project = get_project(ctx)
    record = references_mod.lookup(project, origin)
    if record is None:
        console.print(f"MISS — no cached extraction for {origin}")
        raise typer.Exit(4)
    if as_json:
        print(json.dumps(record, indent=2, default=str))
    else:
        status = f"STALE ({record['stale']})" if record["stale"] else "HIT"
        console.print(f"{status} — {record['id']} at {record['path']} (retrieved {record.get('retrieved')})")
        if not as_json and not record["stale"]:
            console.print(record.get("body", "").strip())
    raise typer.Exit(3 if record["stale"] else 0)


@ref_app.command("list")
def ref_list(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """All cached extractions with staleness."""
    project = get_project(ctx)
    records = references_mod.list_references(project)
    if as_json:
        for r in records:
            r.pop("body", None)
        print(json.dumps(records, indent=2, default=str))
        return
    table = Table("id", "title", "origin", "freshness", "retrieved", "state")
    for r in records:
        stale = references_mod.staleness(r)
        table.add_row(str(r.get("id")), str(r.get("title")), str(r.get("origin")),
                      str(r.get("freshness")), str(r.get("retrieved")), stale or "fresh")
    console.print(table)


@ref_app.command("show")
def ref_show(ctx: typer.Context, ref_id: str) -> None:
    """One cached extraction, body included."""
    project = get_project(ctx)
    record = references_mod.get(project, ref_id)
    if record is None:
        fail(f"Unknown reference: {ref_id}")
    body = record.pop("body", "")
    console.print({k: str(v) for k, v in record.items()})
    console.print("\n" + body.strip())


@ref_app.command("check")
def ref_check(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Expired volatile references and origin files changed on disk."""
    project = get_project(ctx)
    findings = references_mod.check(project)
    if as_json:
        print(json.dumps(findings, indent=2))
        return
    if not findings:
        console.print("[green]✓[/green] reference cache is fresh")
        return
    for f in findings:
        console.print(f"[yellow]•[/yellow] {f['reference']} [{f['kind']}] {f['detail']}")


@ref_app.command("promote")
def ref_promote(ctx: typer.Context, ref_id: str) -> None:
    """Materialise an extraction under sources/ (the reference keeps resolving)."""
    project = get_project(ctx)
    try:
        src_id = references_mod.promote(project, ref_id)
    except GreenhouseError as exc:
        fail(str(exc))
    console.print(f"{ref_id} promoted → [bold]{src_id}[/bold]")


# ---------------------------------------------------------------------------
# lint / xref / bundle
# ---------------------------------------------------------------------------


@app.command()
def lint(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """REQ-id discipline, acceptance criteria, provenance, RFC-2119, TODO and
    assumption inventory, uncited ADRs, confidential verbatim runs.
    Exit 1 on error-level findings."""
    project = get_project(ctx)
    try:
        findings = lint_mod.lint_project(project)
    except GreenhouseError as exc:
        fail(str(exc))
    if as_json:
        print(json.dumps(findings, indent=2))
    else:
        if not findings:
            console.print("[green]✓[/green] lint clean")
        for f in findings:
            style = {"error": "red", "warning": "yellow", "info": "dim"}[f["level"]]
            console.print(
                f"[{style}]{f['level']:<7}[/{style}] {f['file']}:{f['line']} "
                f"[{f['rule']}] {f['message']}"
            )
    if lint_mod.has_errors(findings):
        raise typer.Exit(1)


@app.command()
def xref(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    """Dangling links/anchors and REQ ids referenced but never defined. Exit 1 on findings."""
    project = get_project(ctx)
    problems = xref_mod.xref_project(project)
    if as_json:
        print(json.dumps(problems, indent=2))
    else:
        if not problems:
            console.print("[green]✓[/green] cross-references clean")
        for p in problems:
            console.print(f"[red]✗[/red] {p['file']}:{p['line']} [{p['kind']}] {p['detail']}")
    if problems:
        raise typer.Exit(1)


@app.command()
def bundle(
    ctx: typer.Context,
    allow_blocking: bool = typer.Option(
        False, "--allow-blocking",
        help="Promote despite open blocking questions (leaks are never overridable).",
    ),
) -> None:
    """Promote agreed/locked sections to final/ shards (ref/why markers stripped,
    leak check fail-closed) and build final/SPEC.md with a TOC."""
    project = get_project(ctx)
    try:
        result = bundle_mod.bundle(project, allow_blocking=allow_blocking)
    except GreenhouseError as exc:  # LeakError included
        fail(str(exc))
    console.print(f"Promoted shards: {', '.join(result['shards'])}")
    console.print(f"Built [bold]{result['spec']}[/bold]")
    rows = deliverables_mod.readiness(project)
    if rows:
        console.print("Deliverables (write with `greenhouse deliverable write <id>`):")
        for d in rows:
            console.print(f"  • {_deliverable_status_line(d)}")


# ---------------------------------------------------------------------------
# deliverable list|show|add|remove|edit|plan|write
# ---------------------------------------------------------------------------


@deliverable_app.command("list")
def deliverable_list(
    ctx: typer.Context,
    project_name: str | None = PROJECT_OPT,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """What finalization is expected to hand over, with readiness per deliverable."""
    project = get_project(ctx, project_name)
    rows = deliverables_mod.readiness(project)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print(
            "No deliverables declared. Add with: greenhouse deliverable add <id> "
            "--title ... --section <s> ..."
        )
        return
    for d in rows:
        console.print(f"• {_deliverable_status_line(d)}")
        console.print(f"    {d['title']} → {d['path']}")
        fed = ", ".join(f"{s['section']} ({s['maturity']})" for s in d["sections"]) or "—"
        console.print(f"    fed by: {fed}")


@deliverable_app.command("show")
def deliverable_show(
    ctx: typer.Context,
    deliverable_id: str,
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """One deliverable in full: description, feeding sections, readiness, file."""
    project = get_project(ctx)
    rows = [r for r in deliverables_mod.readiness(project) if r["id"] == deliverable_id]
    if not rows:
        fail(f"Unknown deliverable: {deliverable_id}")
    d = rows[0]
    if as_json:
        print(json.dumps(d, indent=2))
        return
    console.print(f"[bold]{d['id']}[/bold] — {d['title']}")
    console.print(f"  format: {d['format']}")
    console.print(f"  file:   {d['path']}" + ("" if d["exists"] else " (not written yet)"))
    console.print(f"  status: {_deliverable_status_line(d).split(' — ', 1)[1]}")
    console.print(f"  needs:  {d['description'] or '(no description)'}")
    console.print("  fed by:")
    for sec in d["sections"]:
        console.print(f"    - {sec['section']} ({sec['maturity']})")


@deliverable_app.command("add")
def deliverable_add(
    ctx: typer.Context,
    deliverable_id: str = typer.Argument(..., help="kebab-case id, e.g. operator-guide"),
    title: str = typer.Option(..., "--title"),
    description: str = typer.Option(
        "", "--description", help="What the artefact must contain, for whom."
    ),
    fmt: str = typer.Option("markdown", "--format", help="e.g. 'markdown guide', 'mermaid diagram'."),
    path: str | None = typer.Option(None, "--path", help="File name under final/deliverables/ (default <id>.md)."),
    sections: list[str] = typer.Option([], "--section", help="Feeding section id (repeatable)."),
) -> None:
    """Declare a deliverable this project expects at finalization."""
    project = get_project(ctx)
    try:
        project.add_deliverable(
            deliverable_id, title, description=description, fmt=fmt, path=path,
            sections=sections,
        )
        state_mod.validate_project(project)
    except (GreenhouseError, ValidationFailure) as exc:
        fail(str(exc))
    project.save()
    console.print(
        f"Added deliverable [bold]{deliverable_id}[/bold] fed by "
        + (", ".join(sections) or "no sections yet — link with `deliverable edit --add-section`")
    )


@deliverable_app.command("remove")
def deliverable_remove(ctx: typer.Context, deliverable_id: str) -> None:
    """Drop a deliverable from the project's expectations (its file, if any, is left in place)."""
    project = get_project(ctx)
    try:
        node = project.remove_deliverable(deliverable_id)
    except GreenhouseError as exc:
        fail(str(exc))
    project.save()
    console.print(f"Removed deliverable [bold]{deliverable_id}[/bold] ({node.get('title')})")
    target = project.final_dir / deliverables_mod.DELIVERABLES_DIR / (
        node.get("path") or f"{deliverable_id}.md"
    )
    if target.exists():
        console.print(f"[yellow]Note:[/yellow] {target.relative_to(project.root)} still exists; delete it if it should not ship.")


@deliverable_app.command("edit")
def deliverable_edit(
    ctx: typer.Context,
    deliverable_id: str,
    title: str | None = typer.Option(None, "--title"),
    description: str | None = typer.Option(None, "--description"),
    fmt: str | None = typer.Option(None, "--format"),
    path: str | None = typer.Option(None, "--path"),
    sections: list[str] = typer.Option([], "--section", help="Replace the feeding list (repeatable)."),
    add_sections: list[str] = typer.Option([], "--add-section", help="Add a feeding section (repeatable)."),
    drop_sections: list[str] = typer.Option([], "--drop-section", help="Remove a feeding section (repeatable)."),
) -> None:
    """Change a deliverable's title, description, format, file name or feeding sections."""
    project = get_project(ctx)
    try:
        project.edit_deliverable(
            deliverable_id, title=title, description=description, fmt=fmt, path=path,
            sections=sections or None, add_sections=add_sections, drop_sections=drop_sections,
        )
        state_mod.validate_project(project)
    except (GreenhouseError, ValidationFailure) as exc:
        fail(str(exc))
    project.save()
    d = project.spec().deliverable_by_id(deliverable_id)
    console.print(
        f"Updated [bold]{deliverable_id}[/bold] — fed by {', '.join(d.sections) or '—'}"
    )


@deliverable_app.command("plan")
def deliverable_plan(
    ctx: typer.Context,
    deliverable_id: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """What the finalize step needs to write each deliverable: description,
    readiness, and the workfile slice / promoted shard behind every feeding section."""
    project = get_project(ctx)
    try:
        rows = deliverables_mod.plan(project, deliverable_id)
    except GreenhouseError as exc:
        fail(str(exc))
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print("No deliverables declared.")
        return
    for d in rows:
        console.print(f"[bold]{d['id']}[/bold] — {d['title']} ({d['format']}) → {d['path']}")
        console.print(f"  status: {_deliverable_status_line(d).split(' — ', 1)[1]}")
        console.print(f"  needs:  {d['description'] or '(no description)'}")
        console.print("  inputs:")
        for i in d["inputs"]:
            src = i["shard"] or i["workfile"] or "—"
            console.print(f"    - {i['section']} ({i['maturity']}): {src}")


@deliverable_app.command("write")
def deliverable_write(
    ctx: typer.Context,
    deliverable_id: str,
    from_file: Path = typer.Option(
        ..., "--from-file", help="The artefact's content; '-' reads stdin."
    ),
    allow_unready: bool = typer.Option(
        False, "--allow-unready",
        help="Write although a feeding section is not agreed/locked (leaks are never overridable).",
    ),
) -> None:
    """Land a deliverable under final/deliverables/: markers stripped, leak check
    fail-closed, `built_at` stamped, folder README regenerated."""
    project = get_project(ctx)
    content = sys.stdin.read() if str(from_file) == "-" else Path(from_file).read_text()
    try:
        rel = deliverables_mod.write(
            project, deliverable_id, content, allow_unready=allow_unready
        )
    except GreenhouseError as exc:  # LeakError included
        fail(str(exc))
    console.print(f"Wrote [bold]{rel}[/bold]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
