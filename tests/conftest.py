import pytest

from greenhouse import scaffold


@pytest.fixture(autouse=True)
def _isolated_workspace(monkeypatch):
    """Tests never see the developer's real workspace (env var or local config)."""
    monkeypatch.delenv("GREENHOUSE_WORKSPACE", raising=False)


@pytest.fixture
def repo(tmp_path):
    """A bare repo root (a .git marker so workspace resolution stops here —
    legacy layout: projects under <repo>/projects/)."""
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def project(repo):
    """A freshly scaffolded cli-tool project named `demo`."""
    return scaffold.create_project(repo, "demo", archetype="cli-tool")
