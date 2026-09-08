import datetime as dt

import pytest

from greenhouse import scaffold, state
from greenhouse.models import (
    AmbiguousProjectError,
    BlockedError,
    ProjectNotFoundError,
    ValidationFailure,
)


def test_scaffold_creates_contract_folders(project):
    for sub in ("workfiles", "sources", "history/decisions", "history/sessions",
                "history/references", "final"):
        assert (project.root / sub).is_dir(), sub
    assert project.ideas_file.exists()
    assert (project.sources_dir / "INDEX.md").exists()


def test_scaffold_all_sections_none_and_valid(project):
    spec = project.spec()
    assert spec.sections, "taxonomy seeded sections"
    assert all(s.maturity == "none" for s in spec.sections)
    state.validate_project(project)  # anchors in skeleton workfiles must resolve


def test_resolve_from_inside_project_dir(repo, project):
    p = state.resolve_project(cwd=project.workfiles_dir)
    assert p.name == "demo"


def test_resolve_single_project_from_repo_root(repo, project):
    assert state.resolve_project(cwd=repo).name == "demo"


def test_resolve_ambiguous_lists_candidates(repo, project):
    scaffold.create_project(repo, "other", archetype="cli-tool")
    with pytest.raises(AmbiguousProjectError) as exc:
        state.resolve_project(cwd=repo)
    assert set(exc.value.candidates) == {"demo", "other"}
    # explicit override works from anywhere
    assert state.resolve_project("demo", cwd=repo).name == "demo"


def test_resolve_no_projects(repo):
    with pytest.raises(ProjectNotFoundError):
        state.resolve_project(cwd=repo)


def test_blocking_question_blocks_agreed(project):
    qid = project.add_question("auth", "ADC only, or SA keys too?", blocking=True)
    with pytest.raises(BlockedError):
        project.set_maturity("auth", "agreed")
    # non-blocking questions do not block
    project.set_maturity("auth", "draft")
    project.resolve_question(qid)
    project.set_maturity("auth", "agreed")
    project.save()
    assert project.spec().section_by_id("auth").maturity == "agreed"


def test_force_overrides_block(project):
    project.add_question("auth", "blocking?", blocking=True)
    project.set_maturity("auth", "agreed", force=True)
    assert project.spec().section_by_id("auth").agreed_at is not None


def test_downgrade_clears_agreed_at(project):
    project.set_maturity("config", "agreed")
    project.set_maturity("config", "draft")
    assert project.spec().section_by_id("config").agreed_at is None


def test_question_ids_unique_per_stem(project):
    q1 = project.add_question("auth", "one")
    q2 = project.add_question("auth", "two")
    assert q1 == "q-auth-1" and q2 == "q-auth-2"


def test_question_ids_never_reused_after_resolve(project):
    q1 = project.add_question("auth", "one")
    project.resolve_question(q1)
    # the resolved id survives only in history/ — that must still reserve it
    project.sessions_dir.mkdir(parents=True, exist_ok=True)
    (project.sessions_dir / "2026-01-01-x.md").write_text(
        f"---\nquestions_resolved:\n- {q1}\n---\nresolved {q1}\n", encoding="utf-8"
    )
    assert project.add_question("auth", "two") == "q-auth-2"


def test_alias_resolution(project):
    sec = project.raw_section("cli.commands")
    sec["aliases"] = ["cli.cmds"]
    project.save()
    assert project.spec().section_by_id("cli.cmds").id == "cli.commands"
    assert project.raw_section("cli.cmds")["id"] == "cli.commands"


def test_validate_fails_on_bad_depends_on(project):
    project.raw_section("auth")["depends_on"] = ["nope"]
    project.save()
    with pytest.raises(ValidationFailure) as exc:
        state.validate_project(project)
    assert any("nope" in p for p in exc.value.problems)


def test_validate_fails_on_missing_anchor(project):
    project.raw_section("auth")["workfile"] = "workfiles/50-auth-and-config.md#nonexistent"
    project.save()
    with pytest.raises(ValidationFailure):
        state.validate_project(project)


def test_dependents_transitive(project):
    spec = project.spec()
    deps = spec.dependents_of("config")
    assert "auth" in deps and "security" in deps  # auth→config, security→auth


def test_today_env_override(monkeypatch):
    monkeypatch.setenv("GREENHOUSE_TODAY", "2026-01-02")
    assert state.today() == dt.date(2026, 1, 2)


def test_projects_scaffold_under_projects_dir(repo, project):
    assert project.root == repo / "projects" / "demo"
    # legacy location still resolves — discovery is glob-based
    legacy = repo / "elsewhere"
    import shutil
    shutil.copytree(project.root, legacy)
    (legacy / "spec-state.yaml").write_text(
        (legacy / "spec-state.yaml").read_text().replace("project: demo", "project: legacy")
    )
    found = {p.name for p in state.discover_projects(repo)}
    assert found == {"demo", "elsewhere"}


def test_validate_accepts_pending_decision_ids_only_for_that_run(project):
    wf = project.workfiles_dir / "00-overview.md"
    wf.write_text(wf.read_text() + "\nfact <!-- why: 0002 -->\n")
    with pytest.raises(ValidationFailure):
        state.validate_project(project)
    assert state.validate_project(project, pending_decisions=["0002"]) == []


def test_retract_assumption_by_index_text_and_substring(project):
    from greenhouse.models import GreenhouseError

    project.add_assumption("auth", "Analysts have gcloud installed")
    project.add_assumption("auth", "ADC is available on every workstation")
    project.add_assumption("auth", "ADC tokens are refreshed by gcloud")
    # ambiguous substring is refused, nothing removed
    with pytest.raises(GreenhouseError):
        project.retract_assumption("auth", "ADC")
    assert len(project.raw_section("auth")["assumptions"]) == 3
    # exact text
    assert project.retract_assumption("auth", "Analysts have gcloud installed") == (
        "Analysts have gcloud installed"
    )
    # unique substring
    assert project.retract_assumption("auth", "refreshed").endswith("by gcloud")
    # 1-based index on the one that is left
    assert project.retract_assumption("auth", "1").startswith("ADC is available")
    assert project.raw_section("auth")["assumptions"] == []
    with pytest.raises(GreenhouseError):
        project.retract_assumption("auth", "1")
    project.save()
    assert project.spec().section_by_id("auth").assumptions == []


def test_add_dependency_is_a_dag(project):
    from greenhouse.models import GreenhouseError

    assert project.add_dependency("cli.commands", "auth") is True
    assert project.add_dependency("cli.commands", "auth") is False  # idempotent
    assert "auth" in project.raw_section("cli.commands")["depends_on"]
    with pytest.raises(GreenhouseError):
        project.add_dependency("auth", "cli.commands")  # would close a cycle
    with pytest.raises(GreenhouseError):
        project.add_dependency("auth", "auth")
    with pytest.raises(GreenhouseError):
        project.add_dependency("auth", "no-such-section")
    project.save()
    assert state.validate_project(project) == []
