"""Workspace resolution: *where spec projects live*.

The tooling (CLI, templates, skills) and the projects it grows are separate
concerns. A **workspace** is any directory — usually its own git repo — that
holds spec projects; it is marked by a `greenhouse.toml` at its root. This
checkout's `projects/` folder is only the fallback workspace for someone who
has configured nothing.

Resolution order (first hit wins), shared by every CLI command and the MCP
server:

1. `GREENHOUSE_WORKSPACE` environment variable.
2. `workspace = "<path>"` in `greenhouse.local.toml`, found by walking up from
   the CWD (that file lives, git-ignored, in the tooling checkout and also
   remembers a default project).
3. Nearest ancestor of the CWD containing `greenhouse.toml`.
4. Nearest ancestor of the CWD containing `.git` (legacy: the checkout itself
   is the workspace and projects live under `projects/`).
5. The CWD itself.

Nothing here reads spec state; `state.resolve_project` builds on it.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import GreenhouseError

WORKSPACE_FILENAME = "greenhouse.toml"
LOCAL_CONFIG_FILENAME = "greenhouse.local.toml"
ENV_VAR = "GREENHOUSE_WORKSPACE"

_WORKSPACE_TEMPLATE = """\
# Greenhouse Concept workspace marker — spec projects live under this folder.
# Read by `greenhouse` (the tooling repo) to find projects; commit this file.
#
# projects_dir: where `greenhouse new` scaffolds (relative to this file).
projects_dir = "{projects_dir}"

# templates_dir: optional workspace-local archetypes/guidance overriding the
# tooling's `templates/` (same layout: taxonomies/, docs/).
# templates_dir = "templates"

# [integrations]
# obsidian = {{ vault = "~/Vaults/specs" }}
"""

_README_TEMPLATE = """\
# Spec workspace

One folder per spec project, grown with the Greenhouse Concept tooling.
Point the tooling here (`greenhouse workspace use <this folder>`, or
`GREENHOUSE_WORKSPACE=<this folder>`) and run the `/spec-*` skills from the
tooling checkout; every write lands in this repo.
"""


def tooling_root() -> Path:
    """Root of the source checkout this package runs from (holds templates/)."""
    return Path(__file__).resolve().parents[2]


def _walk_up(start: Path, filename: str) -> Path | None:
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / filename).exists():
            return candidate
    return None


def load_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise GreenhouseError(f"{path}: invalid TOML — {exc}") from exc


def find_local_config(cwd: Path | None = None) -> Path | None:
    """`greenhouse.local.toml` in the nearest ancestor of the CWD, if any."""
    found = _walk_up(cwd or Path.cwd(), LOCAL_CONFIG_FILENAME)
    return found / LOCAL_CONFIG_FILENAME if found else None


def local_config_path(cwd: Path | None = None) -> Path:
    """Where `workspace use` / `workspace project` write: the existing local
    config if one is in scope, else the nearest git root (the tooling checkout)."""
    existing = find_local_config(cwd)
    if existing:
        return existing
    cwd = (cwd or Path.cwd()).resolve()
    git_root = _walk_up(cwd, ".git") or cwd
    return git_root / LOCAL_CONFIG_FILENAME


@dataclass
class Workspace:
    root: Path
    source: str  # env | local-config | marker | git | cwd
    config: dict[str, Any] = field(default_factory=dict)  # greenhouse.toml
    local: dict[str, Any] = field(default_factory=dict)  # greenhouse.local.toml
    local_path: Path | None = None

    # -- paths --------------------------------------------------------------

    @property
    def marker(self) -> Path:
        return self.root / WORKSPACE_FILENAME

    @property
    def projects_dir(self) -> Path:
        """Where new projects are scaffolded. A marked workspace holds them at
        its root; the legacy checkout-as-workspace keeps `projects/`."""
        rel = self.config.get("projects_dir")
        if rel is None:
            rel = "." if self.marker.exists() else "projects"
        return (self.root / str(rel)).resolve()

    @property
    def templates_dir(self) -> Path | None:
        """Workspace-local templates, if declared or present; None → tooling's."""
        rel = self.config.get("templates_dir")
        candidate = (self.root / str(rel)).resolve() if rel else self.root / "templates"
        return candidate if candidate.is_dir() else None

    @property
    def integrations(self) -> dict[str, dict[str, Any]]:
        section = self.config.get("integrations", {})
        return {k: dict(v) for k, v in section.items() if isinstance(v, dict)}

    @property
    def default_project(self) -> str | None:
        value = self.local.get("project")
        return str(value) if value else None

    def describe(self) -> str:
        return f"{self.root} (from {self.source})"


def _coerce_path(raw: str, origin: str) -> Path:
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_dir():
        raise GreenhouseError(f"Workspace {path} ({origin}) is not a directory")
    return path


def find_workspace(cwd: Path | None = None) -> Workspace:
    """Resolve the workspace per the module docstring."""
    cwd = (cwd or Path.cwd()).resolve()
    local_path = find_local_config(cwd)
    local = load_toml(local_path) if local_path else {}

    env = os.environ.get(ENV_VAR)
    if env:
        root, source = _coerce_path(env, ENV_VAR), "env"
    elif local.get("workspace"):
        assert local_path is not None
        raw = str(local["workspace"])
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            path = local_path.parent / path
        root, source = _coerce_path(str(path), f"{local_path}"), "local-config"
    elif marked := _walk_up(cwd, WORKSPACE_FILENAME):
        root, source = marked, "marker"
    elif git := _walk_up(cwd, ".git"):
        root, source = git, "git"
    else:
        root, source = cwd, "cwd"

    marker = root / WORKSPACE_FILENAME
    config = load_toml(marker) if marker.exists() else {}
    return Workspace(root=root, source=source, config=config, local=local, local_path=local_path)


def as_workspace(value: Workspace | Path | str | None, cwd: Path | None = None) -> Workspace:
    """Accept a Workspace, a workspace root path, or None (→ resolve from CWD)."""
    if isinstance(value, Workspace):
        return value
    if value is None:
        return find_workspace(cwd)
    root = Path(value).resolve()
    marker = root / WORKSPACE_FILENAME
    return Workspace(
        root=root, source="explicit", config=load_toml(marker) if marker.exists() else {}
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_local_config(path: Path, **updates: Any) -> dict[str, Any]:
    """Merge top-level keys into greenhouse.local.toml (None deletes a key)."""
    data = load_toml(path) if path.exists() else {}
    for key, value in updates.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    lines = [
        "# Local greenhouse settings — per checkout, git-ignored, never shared.",
        "# workspace: where spec projects live; project: default when none is named.",
    ]
    for key, value in data.items():
        if isinstance(value, dict):
            continue  # only flat keys are managed here
        lines.append(f"{key} = {_toml_scalar(value)}")
    path.write_text("\n".join(lines) + "\n")
    return data


def init_workspace(path: Path, projects_dir: str = ".") -> Workspace:
    """Mark `path` as a workspace: greenhouse.toml (+ a README when the folder
    is new). Existing projects inside are left untouched; git is not run."""
    root = Path(path).expanduser().resolve()
    marker = root / WORKSPACE_FILENAME
    if marker.exists():
        raise GreenhouseError(f"{root} is already a workspace ({marker} exists)")
    fresh = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(_WORKSPACE_TEMPLATE.format(projects_dir=projects_dir))
    (root / projects_dir).mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if fresh or not readme.exists():
        readme.write_text(_README_TEMPLATE)
    return as_workspace(root)
