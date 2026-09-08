from greenhouse import history, lint, xref


def _write(project, name, extra):
    wf = project.workfiles_dir / name
    wf.write_text(wf.read_text() + extra)


def _rules(findings, level=None):
    return {f["rule"] for f in findings if level is None or f["level"] == level}


def test_duplicate_req_id_reports_both_locations(project):
    _write(project, "20-requirements.md",
           "\n- **REQ-QUERY-001** — MUST run. Acceptance: exits 0.\n")
    _write(project, "40-cli-reference.md",
           "\n- **REQ-QUERY-001** — MUST also run. Acceptance: exits 0.\n")
    findings = lint.lint_project(project)
    dups = [f for f in findings if f["rule"] == "req-id-duplicate"]
    assert len(dups) == 1
    assert "workfiles/20-requirements.md" in dups[0]["message"]  # first location cited
    assert dups[0]["file"] == "workfiles/40-cli-reference.md"
    assert lint.has_errors(findings)


def test_needs_criterion_and_provenance(project):
    _write(project, "20-requirements.md", "\n- **REQ-AUTH-001** — MUST use ADC.\n")
    rules = _rules(lint.lint_project(project), "warning")
    assert "needs-criterion" in rules and "req-no-provenance" in rules
    # criterion + why marker silence both
    adr = history.write_decision(project, "ADC only", "why", sections=["auth"])
    wf = project.workfiles_dir / "20-requirements.md"
    wf.write_text(wf.read_text().replace(
        "- **REQ-AUTH-001** — MUST use ADC.",
        f"- **REQ-AUTH-001** — MUST use ADC. Acceptance: gcloud auth works. <!-- why: {adr} -->",
    ))
    rules = _rules(lint.lint_project(project))
    assert "needs-criterion" not in rules and "req-no-provenance" not in rules


def test_source_only_justification_flagged(project, tmp_path):
    from greenhouse import sources
    f = tmp_path / "doc.md"
    f.write_text("quota is 1500")
    sources.add_source(project, str(f), title="doc")
    _write(project, "20-requirements.md",
           "\n- **REQ-Q-001** — MUST respect quota. Acceptance: yes. <!-- ref: src-0001 -->\n")
    assert "source-only-justification" in _rules(lint.lint_project(project), "warning")


def test_rfc2119_and_todo_inventory(project):
    _write(project, "00-overview.md", "\nWe should probably cache results. TODO decide.\n")
    rules = _rules(lint.lint_project(project), "info")
    assert "rfc2119" in rules and "todo" in rules


def test_dangling_markers_are_errors(project):
    _write(project, "00-overview.md", "\nfact <!-- why: 0007 --> <!-- ref: src-0009 -->\n")
    findings = lint.lint_project(project)
    assert {"dangling-why", "dangling-ref"} <= _rules(findings, "error")


def test_uncited_accepted_adr_flagged(project):
    history.write_decision(project, "sync default", "ctx", sections=["cli.commands"])
    assert "adr-uncited" in _rules(lint.lint_project(project), "warning")


def test_xref_dangling_link_and_anchor(project):
    _write(project, "00-overview.md",
           "\nSee [details](30-architecture.md#no-such-anchor) and [gone](nope.md).\n"
           "Also [ok](30-architecture.md#architecture-overview).\n")
    problems = xref.xref_project(project)
    kinds = {p["kind"] for p in problems}
    assert kinds == {"dangling-anchor", "dangling-link"}


def test_xref_undefined_req_mention(project):
    _write(project, "00-overview.md", "\nAs REQ-QUERY-042 states, queries stream.\n")
    problems = xref.xref_project(project)
    assert any(p["kind"] == "undefined-req" for p in problems)


def test_why_marker_idea_digits_are_not_adr_ids():
    """`idea-0003` inside a why-marker must not be read as ADR 0003 too."""
    from greenhouse.mdutil import extract_why_ids

    ids = [i for _, i in extract_why_ids("x <!-- why: 0002, idea-0003 --> y")]
    assert ids == ["idea-0003", "0002"]


def test_xref_undefined_req_in_history_is_not_flagged(project):
    """History records options never taken; an undefined id there is faithful."""
    history.write_decision(
        project, "sync default",
        "Options: a new REQ-QUERY-099 with a check / nothing (CHOSEN).",
        sections=["cli.commands"],
    )
    problems = xref.xref_project(project)
    assert not any(p["kind"] == "undefined-req" for p in problems)
