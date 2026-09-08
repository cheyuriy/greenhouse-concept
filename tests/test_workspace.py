"""Workspace resolution: projects live outside the tooling checkout."""

import pytest

from greenhouse import scaffold, state, workspace
from greenhouse.models import GreenhouseError, ProjectNotFoundError


@pytest.fixture
def tooling(tmp_path):
    """Stand-in for the tooling checkout: a git root with no projects."""
    root = tmp_path / "tooling"
    (root / ".git").mkdir(parents=True)
    return root


@pytest.fixture
def ws(tmp_path):
    """An external, marked workspace (its own git repo) holding two projects at its root."""
    root = tmp_path / "specs"
    workspace.init_workspace(root)
    (root / ".git").mkdir()
    scaffold.create_project(root, "alpha", archetype="cli-tool")
    scaffold.create_project(root, "beta", archetype="cli-tool")
    return root


# -- resolution order -------------------------------------------------------


def test_legacy_git_root_is_the_workspace(repo):
    found = workspace.find_workspace(repo / "sub")
    assert found.root == repo and found.source == "git"
    assert found.projects_dir == repo / "projects"


def test_marker_wins_over_git(ws):
    found = workspace.find_workspace(ws / "alpha" / "workfiles")
    assert found.root == ws and found.source == "marker"
    assert found.projects_dir == ws  # marked workspace: projects at the root


def test_env_var_wins_over_everything(monkeypatch, tooling, ws):
    monkeypatch.setenv("GREENHOUSE_WORKSPACE", str(ws))
    found = workspace.find_workspace(tooling)
    assert found.root == ws and found.source == "env"


def test_env_var_must_point_at_a_directory(monkeypatch, tooling, tmp_path):
    monkeypatch.setenv("GREENHOUSE_WORKSPACE", str(tmp_path / "nope"))
    with pytest.raises(GreenhouseError):
        workspace.find_workspace(tooling)


def test_local_config_points_the_checkout_at_a_workspace(tooling, ws):
    cfg = workspace.local_config_path(tooling)
    assert cfg == tooling / "greenhouse.local.toml"
    workspace.write_local_config(cfg, workspace=str(ws))
    found = workspace.find_workspace(tooling / "deep" / "er")
    assert found.root == ws and found.source == "local-config"
    assert found.local_path == cfg


def test_local_config_relative_path_is_relative_to_the_file(tooling, ws):
    cfg = tooling / "greenhouse.local.toml"
    workspace.write_local_config(cfg, workspace="../specs")
    assert workspace.find_workspace(tooling).root == ws


def test_write_local_config_merges_and_deletes(tooling):
    cfg = tooling / "greenhouse.local.toml"
    workspace.write_local_config(cfg, workspace="/w", project="p")
    assert workspace.load_toml(cfg) == {"workspace": "/w", "project": "p"}
    workspace.write_local_config(cfg, project=None)
    assert workspace.load_toml(cfg) == {"workspace": "/w"}


def test_projects_dir_from_marker_config(tmp_path):
    root = tmp_path / "w"
    workspace.init_workspace(root, projects_dir="specs")
    found = workspace.find_workspace(root)
    assert found.projects_dir == root / "specs"
    p = scaffold.create_project(found, "gamma")
    assert p.root == root / "specs" / "gamma"


def test_init_refuses_twice(ws):
    with pytest.raises(GreenhouseError):
        workspace.init_workspace(ws)


# -- project resolution inside an external workspace ------------------------


def test_scaffold_lands_in_the_workspace_not_the_checkout(tooling, ws):
    workspace.write_local_config(tooling / "greenhouse.local.toml", workspace=str(ws))
    found = workspace.find_workspace(tooling)
    p = scaffold.create_project(found, "gamma")
    assert p.root == ws / "gamma"
    assert not (tooling / "projects").exists()


def test_repo_root_is_the_projects_git_root_not_the_cwd(tooling, ws):
    workspace.write_local_config(tooling / "greenhouse.local.toml", workspace=str(ws))
    p = state.resolve_project("alpha", cwd=tooling)
    assert p.repo_root == ws
    assert p.workspace.root == ws
    assert p.resolved_by == "explicit"


def test_cwd_walkup_only_counts_inside_the_workspace(tooling, ws):
    # a project sitting in the tooling checkout is invisible once the
    # workspace points elsewhere — no leak across repos
    scaffold.create_project(tooling, "stray")
    workspace.write_local_config(tooling / "greenhouse.local.toml", workspace=str(ws))
    with pytest.raises(state.AmbiguousProjectError) as exc:
        state.resolve_project(cwd=tooling / "projects" / "stray")
    assert set(exc.value.candidates) == {"alpha", "beta"}
    # inside the workspace the walk-up still works
    assert state.resolve_project(cwd=ws / "beta" / "workfiles").resolved_by == "cwd"


def test_default_project_sits_between_cwd_and_sole(tooling, ws):
    cfg = tooling / "greenhouse.local.toml"
    workspace.write_local_config(cfg, workspace=str(ws), project="beta")
    p = state.resolve_project(cwd=tooling)
    assert p.name == "beta" and p.resolved_by == "default"
    # explicit and CWD still win
    assert state.resolve_project("alpha", cwd=tooling).name == "alpha"
    assert state.resolve_project(cwd=ws / "alpha").name == "alpha"


def test_default_project_must_exist(tooling, ws):
    workspace.write_local_config(
        tooling / "greenhouse.local.toml", workspace=str(ws), project="ghost"
    )
    with pytest.raises(ProjectNotFoundError, match="ghost"):
        state.resolve_project(cwd=tooling)


def test_sole_project_resolves_silently(tooling, tmp_path):
    root = tmp_path / "solo"
    workspace.init_workspace(root)
    scaffold.create_project(root, "only")
    workspace.write_local_config(tooling / "greenhouse.local.toml", workspace=str(root))
    p = state.resolve_project(cwd=tooling)
    assert p.name == "only" and p.resolved_by == "sole"


def test_workspace_templates_override_tooling(tmp_path):
    root = tmp_path / "w"
    workspace.init_workspace(root)
    (root / "templates" / "taxonomies").mkdir(parents=True)
    (root / "templates" / "taxonomies" / "tiny.yaml").write_text(
        "archetype: tiny\n"
        "description: tiny\n"
        "workfiles:\n"
        "  - path: 00-overview.md\n"
        "    title: Overview\n"
        "deliverables: []\n"
        "sections:\n"
        "  - id: overview\n"
        "    title: Overview\n"
        "    heading: Overview\n"
        "    workfile: 00-overview.md\n"
    )
    found = workspace.find_workspace(root)
    assert found.templates_dir == root / "templates"
    p = scaffold.create_project(found, "t", archetype="tiny")
    assert [s.id for s in p.spec().sections] == ["overview"]
    assert state.validate_project(p) == []
