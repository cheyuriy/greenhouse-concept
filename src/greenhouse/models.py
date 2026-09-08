"""Pydantic schema for spec-state.yaml and shared error types.

The YAML file itself is round-tripped with ruamel (see state.py) so human
comments survive; these models are the validation layer every mutation and
`greenhouse validate` run against.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GreenhouseError(Exception):
    """Base for all greenhouse tooling errors."""


class ProjectNotFoundError(GreenhouseError):
    """No project could be resolved from CWD or the given name."""


class AmbiguousProjectError(GreenhouseError):
    """Several projects match and none was named explicitly."""

    def __init__(self, candidates: list[str]):
        self.candidates = candidates
        super().__init__(
            "Ambiguous project — candidates: " + ", ".join(candidates)
        )


class BlockedError(GreenhouseError):
    """A maturity bump was refused because blocking questions are open."""


class DuplicateError(GreenhouseError):
    """A near-duplicate idea (or reused id) was refused."""


class LeakError(GreenhouseError):
    """Source/reference material would leak into final/. Fail-closed."""


class ValidationFailure(GreenhouseError):
    """`greenhouse validate` found unresolvable ids or broken structure."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

Maturity = Literal["none", "stub", "draft", "agreed", "locked"]
MATURITY_ORDER: list[str] = ["none", "stub", "draft", "agreed", "locked"]

IdeaStatus = Literal["open", "deferred", "accepted", "rejected", "superseded", "obsolete"]
SourceKind = Literal["file", "url", "note", "transcript"]
Freshness = Literal["stable", "volatile"]
DecisionStatus = Literal["proposed", "accepted", "superseded", "reverted"]


# ---------------------------------------------------------------------------
# spec-state.yaml models
# ---------------------------------------------------------------------------


class OpenQuestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    text: str
    blocking: bool = False
    raised: dt.date | None = None


class Section(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    maturity: Maturity = "none"
    workfile: str | None = None  # e.g. "workfiles/40-cli-reference.md#query"
    aliases: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)  # session ids
    ideas: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    last_touched: dt.date | None = None
    agreed_at: dt.date | None = None

    @property
    def blocking_questions(self) -> list[OpenQuestion]:
        return [q for q in self.open_questions if q.blocking]


class Idea(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str  # idea-NNNN
    title: str
    status: IdeaStatus = "open"
    relates_to: list[str] = Field(default_factory=list)
    source: str = "user"  # idea-scout | spec-critic | user | drill
    raised: dt.date | None = None
    ref: str | None = None  # workfiles/IDEAS.md#idea-NNNN
    fingerprint: list[str] = Field(default_factory=list)
    resolution: str | None = None  # accepted → ADR id; rejected/obsolete → reason
    last_checked: dt.date | None = None


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str  # src-NNNN
    title: str
    kind: SourceKind = "file"
    path: str | None = None
    url: str | None = None
    added: dt.date | None = None
    added_by: str = "user"
    relates_to: list[str] = Field(default_factory=list)
    checksum: str | None = None  # "sha256:..."
    confidential: bool = False
    note: str | None = None


class Deliverable(BaseModel):
    """An artefact the project expects to receive at finalization, beyond
    SPEC.md — an operator guide, an IaC blueprint, a command reference, an
    architecture diagram. Declared by the archetype taxonomy, copied into the
    project at scaffold time (so /spec-new re-verifies the list), and fed by
    named sections: a drill on a feeding section is told what the deliverable
    needs from it; finalize writes the file once every feeding section is
    agreed/locked."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    description: str = ""
    format: str = "markdown"  # free text: "markdown guide", "mermaid diagram", …
    path: str | None = None  # file name under final/deliverables/; default <id>.md
    sections: list[str] = Field(default_factory=list)  # feeding section ids
    built_at: dt.date | None = None  # stamped by `greenhouse deliverable write`

    @property
    def filename(self) -> str:
        return self.path or f"{self.id}.md"


class TrelloConfig(BaseModel):
    """Optional read-only Trello dashboard for a project (see /spec-trello).

    Trello is a mirror: the skill pushes state onto the board and never reads
    the board back into spec-state.yaml."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    board: str = ""  # exact board name in Trello
    board_url: str | None = None  # recorded after the first sync; skips the name search


class SpecState(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: str
    title: str = ""
    archetype: str = "cli-tool"
    created: dt.date | None = None
    updated: dt.date | None = None
    audience: list[str] = Field(default_factory=list)
    one_liner: str = ""
    sections: list[Section] = Field(default_factory=list)
    ideas: list[Idea] = Field(default_factory=list)
    sources: list[SourceEntry] = Field(default_factory=list)
    deliverables: list[Deliverable] = Field(default_factory=list)
    trello: TrelloConfig | None = None

    # -- id resolution ------------------------------------------------------

    def section_by_id(self, section_id: str) -> Section | None:
        """Resolve a section by id or alias."""
        for s in self.sections:
            if s.id == section_id or section_id in s.aliases:
                return s
        return None

    def idea_by_id(self, idea_id: str) -> Idea | None:
        for i in self.ideas:
            if i.id == idea_id:
                return i
        return None

    def source_by_id(self, source_id: str) -> SourceEntry | None:
        for s in self.sources:
            if s.id == source_id:
                return s
        return None

    def deliverable_by_id(self, deliverable_id: str) -> Deliverable | None:
        for d in self.deliverables:
            if d.id == deliverable_id:
                return d
        return None

    def deliverables_for_section(self, section_id: str) -> list[Deliverable]:
        """Deliverables fed by `section_id` (aliases resolved), in declared order."""
        canonical = self.canonical_section_id(section_id) or section_id
        return [
            d
            for d in self.deliverables
            if any((self.canonical_section_id(s) or s) == canonical for s in d.sections)
        ]

    def question_by_id(self, question_id: str) -> tuple[Section, OpenQuestion] | None:
        for s in self.sections:
            for q in s.open_questions:
                if q.id == question_id:
                    return s, q
        return None

    def canonical_section_id(self, section_id: str) -> str | None:
        s = self.section_by_id(section_id)
        return s.id if s else None

    def dependents_of(self, section_id: str, transitive: bool = True) -> list[str]:
        """Sections that depend on `section_id` (directly or transitively)."""
        canonical = self.canonical_section_id(section_id) or section_id
        direct: dict[str, list[str]] = {}
        for s in self.sections:
            for dep in s.depends_on:
                dep_c = self.canonical_section_id(dep) or dep
                direct.setdefault(dep_c, []).append(s.id)
        if not transitive:
            return sorted(set(direct.get(canonical, [])))
        seen: set[str] = set()
        frontier = [canonical]
        while frontier:
            nxt = frontier.pop()
            for child in direct.get(nxt, []):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return sorted(seen)
