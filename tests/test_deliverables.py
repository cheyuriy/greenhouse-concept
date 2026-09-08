import datetime as dt

import pytest

from greenhouse import bundle, coverage, deliverables, scaffold, sections, sources, state
from greenhouse.models import GreenhouseError, LeakError, ValidationFailure

D1 = dt.date(2026, 8, 1)
D2 = dt.date(2026, 8, 10)
D3 = dt.date(2026, 8, 20)

CMD_REF_SECTIONS = ["cli.global-flags", "cli.commands", "cli.output", "cli.errors", "config", "auth"]


def test_scaffold_copies_archetype_deliverables(project):
    spec = project.spec()
    ids = [d.id for d in spec.deliverables]
    assert ids == ["command-reference", "config-reference", "install-guide"]
    cmd = spec.deliverable_by_id("command-reference")
    assert cmd.sections == CMD_REF_SECTIONS
    assert cmd.filename == "command-reference.md"
    assert cmd.built_at is None
    assert "flag" in cmd.description
    state.validate_project(project)


def test_every_archetype_declares_resolvable_deliverables(repo):
    for archetype in ("cli-tool", "service", "library", "platform-deployment", "saas-hld"):
        p = scaffold.create_project(repo, f"p-{archetype}", archetype=archetype)
        spec = p.spec()
        assert spec.deliverables, f"{archetype} declares no deliverables"
        for d in spec.deliverables:
            assert d.sections, f"{archetype}/{d.id} has no feeding sections"
            assert d.description
        state.validate_project(p)


def test_section_knows_which_deliverables_it_feeds(project):
    spec = project.spec()
    assert [d.id for d in spec.deliverables_for_section("cli.commands")] == [
        "command-reference", "install-guide",
    ]
    assert spec.deliverables_for_section("overview") == []
    info = sections.deps(project, "cli.commands")
    assert [d["id"] for d in info["deliverables"]] == ["command-reference", "install-guide"]
    assert info["deliverables"][0]["description"]


def test_validate_rejects_unknown_feeding_section_and_bad_path(project):
    project.raw_deliverable("config-reference")["sections"].append("nope")
    project.raw_deliverable("install-guide")["path"] = "../escape.md"
    with pytest.raises(ValidationFailure) as exc:
        state.validate_project(project)
    problems = "\n".join(exc.value.problems)
    assert "deliverable config-reference: section 'nope' does not resolve" in problems
    assert "deliverable install-guide" in problems and "relative name" in problems


def test_add_edit_remove_through_state(project):
    project.add_deliverable(
        "threat-model", "Threat model", description="  attack   surface\nand controls ",
        fmt="markdown", sections=["security", "auth"],
    )
    d = project.spec().deliverable_by_id("threat-model")
    assert d.sections == ["security", "auth"]
    assert d.description == "attack surface and controls"
    assert d.filename == "threat-model.md"

    with pytest.raises(GreenhouseError, match="already exists"):
        project.add_deliverable("threat-model", "dup")
    with pytest.raises(GreenhouseError, match="Unknown section"):
        project.add_deliverable("x", "X", sections=["nope"])
    with pytest.raises(GreenhouseError, match="relative name"):
        project.add_deliverable("y", "Y", path="/etc/passwd")
    with pytest.raises(GreenhouseError, match="kebab-case"):
        project.add_deliverable("Bad Id", "Z")

    project.edit_deliverable("threat-model", add_sections=["config"], drop_sections=["auth"])
    assert project.spec().deliverable_by_id("threat-model").sections == ["security", "config"]
    with pytest.raises(GreenhouseError, match="not fed by"):
        project.edit_deliverable("threat-model", drop_sections=["auth"])
    project.edit_deliverable("threat-model", sections=["security"], title="TM")
    d = project.spec().deliverable_by_id("threat-model")
    assert d.sections == ["security"] and d.title == "TM"

    project.remove_deliverable("threat-model")
    assert project.spec().deliverable_by_id("threat-model") is None
    with pytest.raises(GreenhouseError, match="Unknown deliverable"):
        project.remove_deliverable("threat-model")
    state.validate_project(project)


def test_readiness_tracks_feeding_sections(project):
    row = next(r for r in deliverables.readiness(project) if r["id"] == "config-reference")
    assert not row["ready"] and set(row["missing"]) == {"cli.global-flags", "config", "auth", "security"}
    for sid in ("cli.global-flags", "config", "auth", "security"):
        project.set_maturity(sid, "agreed", date=D1)
    project.save()
    row = next(r for r in deliverables.readiness(project) if r["id"] == "config-reference")
    assert row["ready"] and row["missing"] == [] and not row["exists"]


def test_write_refuses_unready_unless_allowed_and_stamps_built_at(project):
    with pytest.raises(GreenhouseError, match="not ready"):
        deliverables.write(project, "config-reference", "# Config\n\ntext\n")
    assert not (project.final_dir / "deliverables" / "config-reference.md").exists()

    rel = deliverables.write(project, "config-reference", "# Config\n\ntext\n", allow_unready=True)
    assert rel == "final/deliverables/config-reference.md"
    out = project.final_dir / "deliverables" / "config-reference.md"
    assert out.read_text() == "# Config\n\ntext\n"
    assert project.spec().deliverable_by_id("config-reference").built_at == state.today()
    index = (project.final_dir / "deliverables" / "README.md").read_text()
    assert "config-reference.md" in index and "GENERATED" in index
    with pytest.raises(GreenhouseError, match="empty"):
        deliverables.write(project, "config-reference", "   \n", allow_unready=True)


def test_write_strips_markers_and_leak_checks(project, tmp_path):
    pricing = tmp_path / "bq-pricing.pdf"
    pricing.write_bytes(b"%PDF-fake")
    sources.add_source(project, str(pricing), title="BQ pricing", relates_to=["config"])
    content = "# Config\n\n`--project` selects the project. <!-- ref: src-0001 -->\n"
    deliverables.write(project, "config-reference", content, allow_unready=True)
    written = (project.final_dir / "deliverables" / "config-reference.md").read_text()
    assert "src-0001" not in written and "<!--" not in written
    with pytest.raises(LeakError, match="src-0001"):
        deliverables.write(project, "config-reference", "Based on src-0001.\n", allow_unready=True)
    with pytest.raises(LeakError, match=r"bq-pricing\.pdf"):
        deliverables.write(project, "config-reference", "see bq-pricing.pdf\n", allow_unready=True)


def test_bundle_leak_check_covers_deliverables_folder(project, tmp_path):
    pricing = tmp_path / "bq-pricing.pdf"
    pricing.write_bytes(b"%PDF-fake")
    sources.add_source(project, str(pricing), title="BQ pricing", relates_to=["config"])
    project.set_maturity("config", "agreed", date=D1)
    project.save()
    bundle.bundle(project)
    rogue = project.final_dir / "deliverables" / "notes.md"
    rogue.parent.mkdir(exist_ok=True)
    rogue.write_text("copied from sources/bq-pricing.pdf\n")
    with pytest.raises(LeakError, match=r"final/deliverables/notes\.md"):
        bundle.bundle(project)


def test_coverage_reports_readiness_feeds_and_stale_builds(project):
    report = coverage.compute(project)
    assert [d["id"] for d in report["deliverables"]] == [
        "command-reference", "config-reference", "install-guide",
    ]
    fill_commands = next(s for s in report["suggestions"] if s["section"] == "cli.commands")
    assert "feeds command-reference, install-guide" in fill_commands["reason"]
    fill_overview = next(s for s in report["suggestions"] if s["section"] == "overview")
    assert "feeds" not in fill_overview["reason"]

    for sid in ("cli.global-flags", "config", "auth", "security"):
        project.set_maturity(sid, "agreed", date=D1)
    project.save()
    deliverables.write(project, "config-reference", "# Config\n\ntext\n")
    project.mark_deliverable_built("config-reference", date=D2)
    project.touch("config", date=D3)
    project.save()
    report = coverage.compute(project)
    row = next(d for d in report["deliverables"] if d["id"] == "config-reference")
    assert row["exists"] and row["stale"] == ["config"]
    rebuild = next(s for s in report["suggestions"] if s["action"] == "rebuild")
    assert rebuild["deliverable"] == "config-reference" and rebuild["section"] is None
    assert "config changed since" in rebuild["reason"]


def test_plan_lists_inputs_with_shards_when_promoted(project):
    project.set_maturity("config", "agreed", date=D1)
    project.save()
    bundle.bundle(project)
    (row,) = deliverables.plan(project, "config-reference")
    by_section = {i["section"]: i for i in row["inputs"]}
    assert by_section["config"]["shard"] == "final/50-auth-and-config.md"
    assert by_section["config"]["workfile"].startswith("workfiles/50-auth-and-config.md#")
    assert by_section["security"]["shard"] is None  # not promoted
    with pytest.raises(GreenhouseError, match="Unknown deliverable"):
        deliverables.plan(project, "nope")
