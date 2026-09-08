"""spec-state.yaml load/save (comment-preserving), project resolution, mutations.

All state changes go through `Project` methods so they are validated and keep
back-links consistent; the AI never hand-edits the YAML.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import mdutil
from .models import (
    AmbiguousProjectError,
    BlockedError,
    GreenhouseError,
    ProjectNotFoundError,
    SpecState,
    ValidationFailure,
)
from .workspace import Workspace, find_workspace

STATE_FILENAME = "spec-state.yaml"
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "templates", ".claude"}

_yaml = YAML(typ="rt")
_yaml.default_flow_style = False
_yaml.preserve_quotes = True


def today() -> dt.date:
    """Today's date; overridable for tests via GREENHOUSE_TODAY=YYYY-MM-DD."""
    override = os.environ.get("GREENHOUSE_TODAY")
    if override:
        return dt.date.fromisoformat(override)
    return dt.date.today()


# ---------------------------------------------------------------------------
# Workspace / project discovery
# (explicit arg → CWD walk-up inside the workspace → local default → sole project → error)
# ---------------------------------------------------------------------------


def find_git_root(start: Path) -> Path | None:
    """Nearest ancestor of `start` containing .git, or None."""
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def find_repo_root(start: Path | None = None) -> Path:
    """Nearest ancestor containing .git; falls back to `start` itself."""
    cur = (start or Path.cwd()).resolve()
    return find_git_root(cur) or cur


def discover_projects(workspace: Workspace | Path) -> list[Path]:
    """Directories under the workspace containing spec-state.yaml (project roots)."""
    root = workspace.root if isinstance(workspace, Workspace) else Path(workspace).resolve()
    roots: list[Path] = []
    for path in sorted(root.rglob(STATE_FILENAME)):
        rel_parts = path.relative_to(root).parts
        if any(p in _SKIP_DIRS or p.startswith(".") for p in rel_parts[:-1]):
            continue
        roots.append(path.parent)
    return roots


def resolve_project(
    explicit: str | None = None,
    cwd: Path | None = None,
    workspace: Workspace | None = None,
) -> Project:
    """The shared §3.7 rule inside the resolved workspace:
    explicit arg → CWD walk-up (only when the CWD is inside the workspace) →
    default project from greenhouse.local.toml → sole project → error.

    Raises AmbiguousProjectError (with candidates) or ProjectNotFoundError; the
    caller decides whether to ask the user or abort.
    """
    cwd = (cwd or Path.cwd()).resolve()
    ws = workspace or find_workspace(cwd)
    projects = discover_projects(ws)

    def by_name(name: str) -> Path | None:
        for root in projects:
            if root.name == name:
                return root
        for root in projects:  # match by the `project:` field too
            try:
                if Project(root, workspace=ws).name == name:
                    return root
            except GreenhouseError:
                continue
        return None

    known = ", ".join(p.name for p in projects) or "(none)"

    if explicit:
        root = by_name(explicit)
        if root is None:
            raise ProjectNotFoundError(
                f"No project named {explicit!r} in workspace {ws.root}. Known: {known}"
            )
        return Project(root, workspace=ws, resolved_by="explicit")

    # walk up from CWD to the workspace root — a CWD outside the workspace
    # carries no signal (it is usually the tooling checkout)
    if cwd == ws.root or ws.root in cwd.parents:
        cur = cwd
        while True:
            if (cur / STATE_FILENAME).exists():
                return Project(cur, workspace=ws, resolved_by="cwd")
            if cur == ws.root or cur.parent == cur:
                break
            cur = cur.parent

    if ws.default_project:
        root = by_name(ws.default_project)
        if root is None:
            raise ProjectNotFoundError(
                f"Default project {ws.default_project!r} ({ws.local_path}) is not in "
                f"workspace {ws.root}. Known: {known}. "
                "Fix with `greenhouse workspace project <name>` or `--clear`."
            )
        return Project(root, workspace=ws, resolved_by="default")

    if len(projects) == 1:
        return Project(projects[0], workspace=ws, resolved_by="sole")
    if not projects:
        raise ProjectNotFoundError(
            f"No projects found in workspace {ws.root}. Create one with: "
            "greenhouse new <name> --archetype cli-tool"
        )
    raise AmbiguousProjectError([p.name for p in projects])


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class Project:
    """A single spec project: paths, round-tripped state, safe mutations."""

    def __init__(
        self,
        root: Path,
        repo_root: Path | None = None,
        *,
        workspace: Workspace | None = None,
        resolved_by: str = "explicit",
    ):
        self.root = Path(root).resolve()
        self.workspace = workspace or find_workspace(self.root)
        # The git root is the project's own (its workspace repo), never the
        # CWD's: every `git -C "$(greenhouse root)"` must hit the repo the
        # spec lives in. `repo_root` is accepted for compatibility only.
        self.repo_root = (
            Path(repo_root).resolve()
            if repo_root
            else find_git_root(self.root) or self.workspace.root
        )
        self.resolved_by = resolved_by  # explicit | cwd | default | sole
        self.state_path = self.root / STATE_FILENAME
        if not self.state_path.exists():
            raise ProjectNotFoundError(f"{self.state_path} does not exist")
        self.data: CommentedMap = _yaml.load(self.state_path.read_text()) or CommentedMap()

    # -- paths --------------------------------------------------------------

    @property
    def workfiles_dir(self) -> Path:
        return self.root / "workfiles"

    @property
    def sources_dir(self) -> Path:
        return self.root / "sources"

    @property
    def history_dir(self) -> Path:
        return self.root / "history"

    @property
    def decisions_dir(self) -> Path:
        return self.history_dir / "decisions"

    @property
    def sessions_dir(self) -> Path:
        return self.history_dir / "sessions"

    @property
    def references_dir(self) -> Path:
        return self.history_dir / "references"

    @property
    def final_dir(self) -> Path:
        return self.root / "final"

    @property
    def ideas_file(self) -> Path:
        return self.workfiles_dir / "IDEAS.md"

    @property
    def name(self) -> str:
        return str(self.data.get("project", self.root.name))

    # -- persistence --------------------------------------------------------

    def save(self) -> None:
        self.data["updated"] = today()
        with self.state_path.open("w") as fh:
            _yaml.dump(self.data, fh)

    def spec(self) -> SpecState:
        """Validated snapshot of the current state."""
        return SpecState.model_validate(_to_plain(self.data))

    # -- raw accessors ------------------------------------------------------

    def _raw_list(self, key: str) -> CommentedSeq:
        if key not in self.data or self.data[key] is None:
            self.data[key] = CommentedSeq()
        return self.data[key]

    def raw_section(self, section_id: str) -> CommentedMap:
        for s in self._raw_list("sections"):
            if s.get("id") == section_id or section_id in (s.get("aliases") or []):
                return s
        raise GreenhouseError(f"Unknown section: {section_id}")

    def raw_idea(self, idea_id: str) -> CommentedMap:
        for i in self._raw_list("ideas"):
            if i.get("id") == idea_id:
                return i
        raise GreenhouseError(f"Unknown idea: {idea_id}")

    def raw_source(self, source_id: str) -> CommentedMap:
        for s in self._raw_list("sources"):
            if s.get("id") == source_id:
                return s
        raise GreenhouseError(f"Unknown source: {source_id}")

    def raw_deliverable(self, deliverable_id: str) -> CommentedMap:
        for d in self._raw_list("deliverables"):
            if d.get("id") == deliverable_id:
                return d
        raise GreenhouseError(f"Unknown deliverable: {deliverable_id}")

    # -- id allocation ------------------------------------------------------

    def next_numbered_id(self, prefix: str, existing: Iterable[str]) -> str:
        """idea-0008 / src-0004 / ref-0002 style ids; never reuses a number."""
        top = 0
        for eid in existing:
            tail = eid.rsplit("-", 1)[-1]
            if tail.isdigit():
                top = max(top, int(tail))
        return f"{prefix}-{top + 1:04d}"

    def next_idea_id(self) -> str:
        return self.next_numbered_id("idea", (i.get("id", "") for i in self._raw_list("ideas")))

    def next_source_id(self) -> str:
        return self.next_numbered_id("src", (s.get("id", "") for s in self._raw_list("sources")))

    def next_adr_id(self) -> str:
        top = 0
        if self.decisions_dir.exists():
            for f in self.decisions_dir.glob("*.md"):
                head = f.name.split("-", 1)[0]
                if head.isdigit():
                    top = max(top, int(head))
        return f"{top + 1:04d}"

    def next_ref_id(self) -> str:
        existing = []
        if self.references_dir.exists():
            existing = [
                f.name.split("-", 2)[0] + "-" + f.name.split("-", 2)[1]
                for f in self.references_dir.glob("ref-*.md")
            ]
        return self.next_numbered_id("ref", existing)

    def next_question_id(self, section_id: str) -> str:
        """Ids are permanent: a resolved question leaves spec-state.yaml but
        its id lives on in history/, so never hand it out again."""
        stem = section_id.rsplit(".", 1)[-1]
        used = {
            q.get("id") for s in self._raw_list("sections") for q in (s.get("open_questions") or [])
        }
        pattern = re.compile(rf"\bq-{re.escape(stem)}-(\d+)\b")
        if self.history_dir.exists():
            for f in self.history_dir.rglob("*.md"):
                try:
                    text = f.read_text(encoding="utf-8")
                except OSError:
                    continue
                used.update(f"q-{stem}-{m}" for m in pattern.findall(text))
        n = 1
        while f"q-{stem}-{n}" in used:
            n += 1
        return f"q-{stem}-{n}"

    # -- mutations ----------------------------------------------------------

    def touch(self, section_id: str, date: dt.date | None = None) -> None:
        sec = self.raw_section(section_id)
        sec["last_touched"] = date or today()

    def set_maturity(
        self,
        section_id: str,
        maturity: str,
        force: bool = False,
        date: dt.date | None = None,
    ) -> None:
        """Bump/downgrade maturity. Refuses agreed/locked while blocking
        questions are open, unless force=True."""
        sec = self.raw_section(section_id)
        date = date or today()
        if maturity in ("agreed", "locked") and not force:
            blocking = [q.get("id") for q in (sec.get("open_questions") or []) if q.get("blocking")]
            if blocking:
                raise BlockedError(
                    f"Cannot mark {section_id!r} {maturity}: blocking open questions "
                    f"remain: {', '.join(blocking)}"
                )
        sec["maturity"] = maturity
        sec["last_touched"] = date
        if maturity in ("agreed", "locked"):
            sec["agreed_at"] = date
        else:
            sec["agreed_at"] = None

    def add_question(
        self,
        section_id: str,
        text: str,
        blocking: bool = False,
        date: dt.date | None = None,
    ) -> str:
        sec = self.raw_section(section_id)
        qid = self.next_question_id(sec["id"])
        questions = sec.get("open_questions")
        if questions is None:
            questions = CommentedSeq()
            sec["open_questions"] = questions
        q = CommentedMap(id=qid, text=text, blocking=blocking, raised=date or today())
        questions.append(q)
        sec["last_touched"] = date or today()
        return qid

    def resolve_question(self, question_id: str) -> tuple[str, str]:
        """Remove a question from its section; returns (section_id, text)."""
        for sec in self._raw_list("sections"):
            questions = sec.get("open_questions") or []
            for i, q in enumerate(list(questions)):
                if q.get("id") == question_id:
                    text = q.get("text", "")
                    del questions[i]
                    sec["last_touched"] = today()
                    return sec["id"], text
        raise GreenhouseError(f"Unknown question: {question_id}")

    def add_dependency(self, section_id: str, dep_id: str) -> bool:
        """Add ``dep_id`` to ``section_id``'s depends_on; returns False when the
        edge already exists. Refuses unknown ids, self-edges, and any edge
        that would close a cycle (depends_on must stay a DAG)."""
        sec = self.raw_section(section_id)
        dep = self.raw_section(dep_id)
        sid, did = sec["id"], dep["id"]
        if sid == did:
            raise GreenhouseError(f"section {sid!r} cannot depend on itself")
        deps = sec.get("depends_on")
        if deps is None:
            deps = CommentedSeq()
            sec["depends_on"] = deps
        if did in deps:
            return False
        # cycle check: is sid reachable from did through existing edges?
        stack, seen = [did], set()
        while stack:
            cur = stack.pop()
            if cur == sid:
                raise GreenhouseError(
                    f"{sid} -> {did} would close a cycle: {did} already depends on {sid}"
                )
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self.raw_section(cur).get("depends_on") or [])
        deps.append(did)
        sec["last_touched"] = today()
        return True

    def add_assumption(self, section_id: str, text: str) -> None:
        sec = self.raw_section(section_id)
        assumptions = sec.get("assumptions")
        if assumptions is None:
            assumptions = CommentedSeq()
            sec["assumptions"] = assumptions
        assumptions.append(text)

    def retract_assumption(self, section_id: str, match: str) -> str:
        """Remove one assumption from a section; returns the removed text.

        ``match`` is a 1-based index, the exact text, or a substring that
        matches exactly one recorded assumption.
        """
        sec = self.raw_section(section_id)
        assumptions = sec.get("assumptions") or []
        if not assumptions:
            raise GreenhouseError(f"No assumptions recorded on {section_id!r}")
        if match.isdigit():
            idx = int(match) - 1
            if not 0 <= idx < len(assumptions):
                raise GreenhouseError(
                    f"{section_id!r} has {len(assumptions)} assumption(s); "
                    f"index {match} is out of range"
                )
        else:
            hits = [i for i, a in enumerate(assumptions) if a == match]
            if not hits:
                hits = [i for i, a in enumerate(assumptions) if match in a]
            if len(hits) != 1:
                raise GreenhouseError(
                    f"{'No' if not hits else 'Several'} assumption(s) on "
                    f"{section_id!r} match {match!r}; pass the 1-based index"
                )
            idx = hits[0]
        text = assumptions[idx]
        del assumptions[idx]
        sec["last_touched"] = today()
        return text

    def link_decision(self, section_ids: list[str], adr_id: str) -> None:
        for sid in section_ids:
            sec = self.raw_section(sid)
            _append_unique(sec, "decisions", adr_id)

    def link_session(self, section_ids: list[str], session_id: str) -> None:
        for sid in section_ids:
            sec = self.raw_section(sid)
            _append_unique(sec, "history", session_id)

    def link_idea_to_section(self, section_id: str, idea_id: str) -> None:
        sec = self.raw_section(section_id)
        _append_unique(sec, "ideas", idea_id)

    # -- deliverables ---------------------------------------------------------

    def _check_deliverable_sections(self, sections: Iterable[str]) -> list[str]:
        out: list[str] = []
        for sid in sections:
            canonical = self.raw_section(sid)["id"]  # raises on unknown
            if canonical not in out:
                out.append(canonical)
        return out

    def add_deliverable(
        self,
        deliverable_id: str,
        title: str,
        description: str = "",
        fmt: str = "markdown",
        path: str | None = None,
        sections: Iterable[str] = (),
    ) -> CommentedMap:
        """Declare a deliverable the project expects at finalization. Refuses a
        reused id, an unknown feeding section, and an unsafe file name."""
        if not re.fullmatch(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", deliverable_id):
            raise GreenhouseError(
                f"Deliverable id {deliverable_id!r} must be kebab-case (dots allowed)"
            )
        for d in self._raw_list("deliverables"):
            if d.get("id") == deliverable_id:
                raise GreenhouseError(f"Deliverable {deliverable_id!r} already exists")
        if not title.strip():
            raise GreenhouseError("Deliverable title must not be empty")
        check_deliverable_path(path)
        node = CommentedMap()
        node["id"] = deliverable_id
        node["title"] = title.strip()
        node["format"] = fmt.strip() or "markdown"
        node["path"] = path or f"{deliverable_id}.md"
        node["description"] = " ".join(description.split())
        node["sections"] = CommentedSeq(self._check_deliverable_sections(sections))
        node["built_at"] = None
        self._raw_list("deliverables").append(node)
        return node

    def remove_deliverable(self, deliverable_id: str) -> CommentedMap:
        seq = self._raw_list("deliverables")
        for i, d in enumerate(list(seq)):
            if d.get("id") == deliverable_id:
                del seq[i]
                return d
        raise GreenhouseError(f"Unknown deliverable: {deliverable_id}")

    def edit_deliverable(
        self,
        deliverable_id: str,
        title: str | None = None,
        description: str | None = None,
        fmt: str | None = None,
        path: str | None = None,
        sections: Iterable[str] | None = None,
        add_sections: Iterable[str] = (),
        drop_sections: Iterable[str] = (),
    ) -> CommentedMap:
        """Change the fields passed; `sections` replaces the feeding list,
        `add_sections`/`drop_sections` adjust it."""
        node = self.raw_deliverable(deliverable_id)
        if title is not None:
            if not title.strip():
                raise GreenhouseError("Deliverable title must not be empty")
            node["title"] = title.strip()
        if description is not None:
            node["description"] = " ".join(description.split())
        if fmt is not None:
            node["format"] = fmt.strip() or "markdown"
        if path is not None:
            check_deliverable_path(path)
            node["path"] = path
        current = list(node.get("sections") or [])
        if sections is not None:
            current = self._check_deliverable_sections(sections)
        for sid in self._check_deliverable_sections(add_sections):
            if sid not in current:
                current.append(sid)
        for sid in drop_sections:
            canonical = self.raw_section(sid)["id"]
            if canonical not in current:
                raise GreenhouseError(f"Deliverable {deliverable_id!r} is not fed by {canonical!r}")
            current.remove(canonical)
        node["sections"] = CommentedSeq(current)
        return node

    def mark_deliverable_built(self, deliverable_id: str, date: dt.date | None = None) -> None:
        self.raw_deliverable(deliverable_id)["built_at"] = date or today()

    def configure_trello(
        self,
        board: str | None = None,
        enabled: bool | None = None,
        board_url: str | None = None,
    ) -> CommentedMap:
        """Create or update the `trello:` block (board name, enabled flag,
        recorded board URL). Only the fields passed change."""
        node = self.data.get("trello")
        if node is None:
            node = CommentedMap(enabled=False, board="", board_url=None)
            # keep it with the project header, above the section list
            keys = list(self.data.keys())
            idx = keys.index("sections") if "sections" in keys else len(keys)
            self.data.insert(idx, "trello", node)
        if board is not None:
            if not board.strip():
                raise GreenhouseError("Board name must not be empty")
            node["board"] = board.strip()
        if enabled is not None:
            node["enabled"] = bool(enabled)
        if board_url is not None:
            node["board_url"] = board_url.strip() or None
        if node.get("enabled") and not node.get("board"):
            raise GreenhouseError("Cannot enable the Trello dashboard without a board name")
        return node


def check_deliverable_path(path: str | None) -> None:
    """A deliverable's file name is relative to final/deliverables/ — never
    absolute, never climbing out of it."""
    if path is None:
        return
    if not path.strip():
        raise GreenhouseError("Deliverable path must not be empty")
    parts = Path(path).parts
    if Path(path).is_absolute() or any(part in ("..", "") for part in parts):
        raise GreenhouseError(
            f"Deliverable path {path!r} must be a relative name inside final/deliverables/"
        )


def _append_unique(node: CommentedMap, key: str, value: Any) -> None:
    seq = node.get(key)
    if seq is None:
        seq = CommentedSeq()
        node[key] = seq
    if value not in seq:
        seq.append(value)


def _to_plain(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _to_plain(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_to_plain(v) for v in node]
    return node


# ---------------------------------------------------------------------------
# Validation  (`greenhouse validate`)
# ---------------------------------------------------------------------------


def validate_project(project: Project, pending_decisions: Iterable[str] = ()) -> list[str]:
    """Full structural validation; returns [] or raises ValidationFailure.

    Checks: schema; unique ids; resolvable depends_on; existing workfiles and
    anchors; resolvable ids in history frontmatter, back-links, and provenance
    markers (aliases included). `pending_decisions` are ADR ids accepted as
    resolvable for this run only (a draft citing the ADR about to be written).
    """
    problems: list[str] = []

    try:
        spec = project.spec()
    except Exception as exc:  # pydantic error → readable lines
        raise ValidationFailure([f"schema: {exc}"]) from exc

    # unique section ids / aliases
    seen: dict[str, str] = {}
    for s in spec.sections:
        for sid in [s.id, *s.aliases]:
            if sid in seen and seen[sid] != s.id:
                problems.append(f"duplicate section id/alias {sid!r} ({seen[sid]} vs {s.id})")
            seen[sid] = s.id

    # unique question ids
    qseen: set[str] = set()
    for s in spec.sections:
        for q in s.open_questions:
            if q.id in qseen:
                problems.append(f"duplicate question id {q.id!r}")
            qseen.add(q.id)

    # depends_on resolve
    for s in spec.sections:
        for dep in s.depends_on:
            if not spec.section_by_id(dep):
                problems.append(f"section {s.id}: depends_on {dep!r} does not resolve")

    # workfile paths + anchors
    for s in spec.sections:
        if not s.workfile:
            continue
        path, _, anchor = s.workfile.partition("#")
        fpath = project.root / path
        if not fpath.exists():
            problems.append(f"section {s.id}: workfile {path!r} missing")
            continue
        if anchor and anchor not in mdutil.anchors_in(fpath.read_text()):
            problems.append(f"section {s.id}: anchor #{anchor} not found in {path}")

    # deliverables: unique ids, feeding sections resolve, safe file names
    dseen: set[str] = set()
    for d in spec.deliverables:
        if d.id in dseen:
            problems.append(f"duplicate deliverable id {d.id!r}")
        dseen.add(d.id)
        for sid in d.sections:
            if not spec.section_by_id(sid):
                problems.append(f"deliverable {d.id}: section {sid!r} does not resolve")
        try:
            check_deliverable_path(d.path)
        except GreenhouseError as exc:
            problems.append(f"deliverable {d.id}: {exc}")

    # known-id inventory
    from . import history as history_mod  # local import: history builds on state

    known = history_mod.known_ids(project, spec, pending_decisions)

    def check(owner: str, kind: str, ids: Iterable[str]) -> None:
        for i in ids:
            if i not in known[kind]:
                problems.append(f"{owner}: {kind} id {i!r} does not resolve")

    # back-links in state
    for s in spec.sections:
        check(f"section {s.id}", "decision", s.decisions)
        check(f"section {s.id}", "session", s.history)
        check(f"section {s.id}", "idea", s.ideas)
    for i in spec.ideas:
        for rel in i.relates_to:
            if not spec.section_by_id(rel):
                problems.append(f"idea {i.id}: relates_to {rel!r} does not resolve")
        if i.ref:
            path, _, anchor = i.ref.partition("#")
            fpath = project.root / path
            if not fpath.exists():
                problems.append(f"idea {i.id}: ref file {path!r} missing")
            elif anchor and anchor not in mdutil.anchors_in(fpath.read_text()):
                problems.append(f"idea {i.id}: anchor #{anchor} not found in {path}")
    for src in spec.sources:
        if src.kind == "file" and src.path and not (project.root / src.path).exists():
            problems.append(f"source {src.id}: file {src.path!r} missing")
        for rel in src.relates_to:
            if not spec.section_by_id(rel):
                problems.append(f"source {src.id}: relates_to {rel!r} does not resolve")

    # history frontmatter ids
    for fpath, fm in history_mod.iter_history_frontmatter(project):
        rel = fpath.relative_to(project.root)
        for key, kind in history_mod.LINK_FIELDS.items():
            for i in fm.get(key) or []:
                target = str(i)
                if kind == "section" and not spec.section_by_id(target):
                    problems.append(f"{rel}: section id {target!r} does not resolve")
                elif kind != "section" and target not in known[kind]:
                    problems.append(f"{rel}: {kind} id {target!r} does not resolve")
        for t in fm.get("maturity_transitions") or []:
            sid = t.get("section") if isinstance(t, dict) else None
            if sid and not spec.section_by_id(str(sid)):
                problems.append(f"{rel}: transition section {sid!r} does not resolve")

    # provenance markers in workfiles
    if project.workfiles_dir.exists():
        for wf in sorted(project.workfiles_dir.glob("*.md")):
            text = wf.read_text()
            rel = wf.relative_to(project.root)
            for lineno, wid in mdutil.extract_why_ids(text):
                kind = "idea" if wid.startswith("idea-") else "decision"
                if wid not in known[kind]:
                    problems.append(
                        f"{rel}:{lineno + 1}: why-marker {kind} id {wid!r} does not resolve"
                    )
            for lineno, rid in mdutil.extract_ref_ids(text):
                kind = "source" if rid.startswith("src-") else "reference"
                if rid not in known[kind]:
                    problems.append(
                        f"{rel}:{lineno + 1}: ref-marker {kind} id {rid!r} does not resolve"
                    )

    if problems:
        raise ValidationFailure(problems)
    return problems
