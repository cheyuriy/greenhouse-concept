"""The integrations seam: the Exporter protocol every future
Notion/Obsidian/Trello/Asana module implements, plus resolution by name.

No vendor SDKs, no credentials, no network code live here — adding a real
exporter is one module implementing `Exporter` plus one entry point.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..models import GreenhouseError
from ..workspace import Workspace, as_workspace


@dataclass
class Document:
    """A spec document to push somewhere (typically a final/ shard or SPEC.md)."""

    title: str
    path: str  # project-relative, e.g. "final/SPEC.md"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenQuestionItem:
    """An open question to mirror as a task in a tracker."""

    id: str
    section: str
    text: str
    blocking: bool = False


@dataclass
class ExportResult:
    ok: bool
    detail: str = ""
    remote_ref: str | None = None  # URL/id on the remote system, if any


@runtime_checkable
class Exporter(Protocol):
    """The contract. Implementations are constructed with their config dict
    from [tool.greenhouse.integrations.<name>] in pyproject.toml."""

    name: str

    def push_document(self, project: str, doc: Document) -> ExportResult: ...

    def upsert_task(self, project: str, question: OpenQuestionItem) -> ExportResult: ...

    def health(self) -> bool: ...


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def load_config(workspace: Workspace | Path) -> dict[str, dict[str, Any]]:
    """`[integrations]` from the workspace's greenhouse.toml, else
    `[tool.greenhouse.integrations]` from a pyproject.toml at its root (legacy)."""
    ws = as_workspace(workspace)
    if ws.integrations:
        return ws.integrations
    pyproject = ws.root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    data = tomllib.loads(pyproject.read_text())
    section = data.get("tool", {}).get("greenhouse", {}).get("integrations", {})
    return {k: dict(v) for k, v in section.items() if isinstance(v, dict)}


def available_exporters() -> dict[str, Any]:
    """Exporter classes registered under the 'greenhouse.exporters' entry point."""
    found: dict[str, Any] = {}
    for ep in entry_points(group="greenhouse.exporters"):
        found[ep.name] = ep.load()
    return found


def get_exporter(name: str, workspace: Workspace | Path) -> Exporter:
    registry = available_exporters()
    if name not in registry:
        raise GreenhouseError(
            f"Unknown exporter {name!r}. Available: {', '.join(sorted(registry)) or '(none)'}"
        )
    config = load_config(workspace).get(name, {})
    exporter = registry[name](config)
    if not isinstance(exporter, Exporter):
        raise GreenhouseError(f"{name!r} does not implement the Exporter protocol")
    return exporter
