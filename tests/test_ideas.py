import datetime as dt

import pytest

from greenhouse import ideas, state
from greenhouse.models import DuplicateError, GreenhouseError


def test_add_idea_writes_both_index_and_prose(project):
    idea_id = ideas.add_idea(
        project, "Dry-run cost estimate before every query",
        body="Show bytes scanned before running.", relates_to=["cli.commands"],
        source="idea-scout",
    )
    assert idea_id == "idea-0001"
    spec = project.spec()
    idea = spec.idea_by_id(idea_id)
    assert idea.status == "open" and idea.fingerprint
    assert idea_id in spec.section_by_id("cli.commands").ideas  # back-link
    assert f"## {idea_id}:" in project.ideas_file.read_text()
    state.validate_project(project)  # ref anchor resolves


def test_near_duplicate_refused_even_when_rejected(project):
    ideas.add_idea(project, "Dry-run cost estimate before every query")
    ideas.set_status(project, "idea-0001", "rejected", resolution="too noisy for small queries")
    with pytest.raises(DuplicateError) as exc:
        ideas.add_idea(project, "Cost estimate dry-run before each query")
    msg = str(exc.value)
    assert "idea-0001" in msg and "too noisy" in msg  # prior rejection surfaces
    # explicit override still possible
    new_id = ideas.add_idea(
        project, "Cost estimate dry-run before each query", allow_duplicate=True
    )
    assert new_id == "idea-0002"


def test_distinct_ideas_not_refused(project):
    ideas.add_idea(project, "Dry-run cost estimate before every query")
    ideas.add_idea(project, "Interactive schema browser for datasets")  # unrelated


def test_accepted_requires_adr(project):
    ideas.add_idea(project, "Saved query snippets")
    with pytest.raises(GreenhouseError):
        ideas.set_status(project, "idea-0001", "accepted")
    with pytest.raises(GreenhouseError):
        ideas.set_status(project, "idea-0001", "accepted", resolution="sounds good")
    ideas.set_status(project, "idea-0001", "accepted", resolution="0003")
    assert project.spec().idea_by_id("idea-0001").resolution == "0003"


def test_rejected_requires_reason(project):
    ideas.add_idea(project, "Saved query snippets")
    with pytest.raises(GreenhouseError):
        ideas.set_status(project, "idea-0001", "rejected")


def test_status_updates_ideas_md(project):
    ideas.add_idea(project, "Saved query snippets")
    ideas.set_status(project, "idea-0001", "rejected", resolution="out of scope")
    block = ideas._idea_block(project.ideas_file.read_text(), "idea-0001")
    assert "**Status:** rejected" in block and "out of scope" in block
    assert ideas.sync_problems(project) == []


def test_audit_flags_locked_and_stale(project):
    d1, d2 = dt.date(2026, 8, 1), dt.date(2026, 8, 20)
    ideas.add_idea(project, "Saved query snippets", relates_to=["cli.commands"], date=d1)
    # section moves after the idea was last checked
    project.touch("cli.commands", date=d2)
    project.save()
    kinds = {f["kind"] for f in ideas.audit(project) if f["idea"] == "idea-0001"}
    assert "stale-relevance" in kinds
    # lock the target section → flagged too
    project.set_maturity("cli.commands", "locked", date=d2)
    project.save()
    kinds = {f["kind"] for f in ideas.audit(project) if f["idea"] == "idea-0001"}
    assert "target-locked" in kinds


def test_audit_flags_orphans(project):
    ideas.add_idea(project, "Saved query snippets", relates_to=["cli.commands"])
    raw = project.raw_idea("idea-0001")
    raw["relates_to"] = ["gone.section"]
    project.save()
    kinds = {f["kind"] for f in ideas.audit(project)}
    assert "orphaned" in kinds


def test_sync_detects_drift(project):
    ideas.add_idea(project, "Saved query snippets")
    text = project.ideas_file.read_text().replace("**Status:** open", "**Status:** rejected")
    project.ideas_file.write_text(text)
    problems = ideas.sync_problems(project)
    assert problems and "idea-0001" in problems[0]
