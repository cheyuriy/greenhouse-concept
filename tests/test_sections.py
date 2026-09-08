"""Section slices are located by the spec-state anchor, bounded by the next
heading of the same or higher level, and replaced without touching neighbours."""

import pytest

from greenhouse import sections
from greenhouse.models import GreenhouseError


def _first_two(project):
    spec = project.spec()
    by_file: dict[str, list] = {}
    for s in spec.sections:
        if s.workfile:
            by_file.setdefault(s.workfile.partition("#")[0], []).append(s)
    for secs in by_file.values():
        if len(secs) >= 2:
            return secs[0], secs[1]
    pytest.skip("archetype has no workfile with two sections")


def test_show_is_bounded_by_the_next_sibling_heading(project):
    a, b = _first_two(project)
    text = sections.show(project, a.id)
    assert text.startswith(f"## {a.title}")
    assert f"## {b.title}" not in text
    assert "<!-- guidance:" in text
    assert sections.guidance(project, a.id)


def test_write_replaces_only_the_slice_and_keeps_guidance(project):
    a, b = _first_two(project)
    path = project.root / a.workfile.partition("#")[0]
    before_b = sections.show(project, b.id)
    diff = sections.write(project, a.id, f"## {a.title}\n\nNew prose here.\n")
    assert "+New prose here." in diff and "_Not yet drafted._" in diff
    after = sections.show(project, a.id)
    assert "New prose here." in after
    assert "<!-- guidance:" in after  # re-inserted since the new text dropped it
    assert sections.show(project, b.id) == before_b
    full = path.read_text()
    assert f"\n\n## {b.title}" in full  # one blank line before the neighbour
    # nested headings stay inside the slice
    sections.write(project, a.id, f"## {a.title}\n\n### Detail\n\nmore\n")
    assert "### Detail" in sections.show(project, a.id)
    assert sections.show(project, b.id) == before_b


def test_write_refuses_wrong_or_early_ending_heading(project):
    a, b = _first_two(project)
    with pytest.raises(GreenhouseError, match="Heading mismatch"):
        sections.write(project, a.id, "## Something else\n\nx\n")
    with pytest.raises(GreenhouseError, match="must start with"):
        sections.write(project, a.id, f"prose first\n## {a.title}\n")
    with pytest.raises(GreenhouseError, match="end the section early"):
        sections.write(project, a.id, f"## {a.title}\n\nx\n\n## {b.title}\n")
    with pytest.raises(GreenhouseError, match="Unknown section"):
        sections.show(project, "nope")


def test_write_dry_run_changes_nothing(project):
    a, _ = _first_two(project)
    path = project.root / a.workfile.partition("#")[0]
    before = path.read_text()
    diff = sections.write(project, a.id, f"## {a.title}\n\nDry.\n", dry_run=True)
    assert "+Dry." in diff and path.read_text() == before
    assert sections.write(project, a.id, sections.show(project, a.id)) == ""


def test_deps_lists_upstream_and_dependents(project):
    spec = project.spec()
    leaf = next(s for s in spec.sections if s.depends_on)
    info = sections.deps(project, leaf.id)
    assert [r["section"] for r in info["depends_on"]] == leaf.depends_on
    assert set(leaf.depends_on) <= {r["section"] for r in info["upstream"]}
    parent = leaf.depends_on[0]
    pinfo = sections.deps(project, parent)
    assert leaf.id in {r["section"] for r in pinfo["dependents"]} | \
        {r["section"] for r in pinfo["transitive_dependents"]}
    assert all(r["maturity"] == "none" for r in pinfo["dependents"])
