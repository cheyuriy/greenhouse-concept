import datetime as dt

import pytest

from greenhouse import coverage, references, sources
from greenhouse.models import GreenhouseError


@pytest.fixture
def pricing_file(tmp_path):
    f = tmp_path / "bq-pricing.md"
    f.write_text("# Pricing\nOn-demand queries cost $6.25 per TiB scanned as of 2026.\n")
    return f


def test_add_source_copies_indexes_checksums(project, pricing_file):
    src_id = sources.add_source(
        project, str(pricing_file), title="BQ pricing Aug 2026",
        relates_to=["cli.commands"],
    )
    assert src_id == "src-0001"
    spec = project.spec()
    src = spec.source_by_id(src_id)
    assert src.path == "sources/bq-pricing.md"
    assert (project.root / src.path).exists()
    assert src.checksum.startswith("sha256:")
    assert "src-0001" in (project.sources_dir / "INDEX.md").read_text()


def test_source_check_flags_drift_and_coverage_goes_stale(project, pricing_file):
    src_id = sources.add_source(project, str(pricing_file), title="BQ pricing",
                                relates_to=["cli.commands"])
    project.set_maturity("cli.commands", "agreed", date=dt.date(2026, 8, 10))
    project.save()
    assert sources.check(project) == []
    # the file changes underneath us
    (project.root / "sources/bq-pricing.md").write_text("# Pricing\nNow $8.00 per TiB.\n")
    findings = sources.check(project)
    assert findings == [{"source": src_id, "kind": "drifted",
                         "detail": "sources/bq-pricing.md changed since registration"}]
    stale = coverage.compute(project)["stale"]
    assert {"section": "cli.commands", "reason": "source-drifted", "source": src_id} in stale


def test_source_orphans_both_directions(project, pricing_file):
    sources.add_source(project, str(pricing_file), title="BQ pricing")
    wf = project.workfiles_dir / "40-cli-reference.md"
    wf.write_text(wf.read_text() + "\nCosts matter. <!-- ref: src-0009 -->\n")
    report = sources.orphans(project)
    assert report["uncited"] == ["src-0001"]  # registered, never cited
    assert report["dangling"][0]["id"] == "src-0009"  # cited, never registered


def test_confidential_verbatim_guard(project, tmp_path):
    secret = tmp_path / "interview.md"
    secret.write_text(
        "The analysts said the worst part of the current workflow is copying "
        "query results into spreadsheets by hand every single morning before standup."
    )
    sources.add_source(project, str(secret), title="Interview", confidential=True)
    wf = project.workfiles_dir / "10-users-and-jobs.md"
    # paraphrase → fine
    wf.write_text(wf.read_text() + "\nAnalysts hand-copy results into sheets daily.\n")
    assert sources.confidential_leaks(project) == []
    # verbatim run → flagged
    wf.write_text(wf.read_text() + "\n> the worst part of the current workflow is copying "
                                   "query results into spreadsheets by hand every single morning\n")
    leaks = sources.confidential_leaks(project)
    assert leaks and leaks[0]["source"] == "src-0001"


def test_ref_lookup_miss_hit_expiry(project, monkeypatch):
    monkeypatch.setenv("GREENHOUSE_TODAY", "2026-09-15")  # 2026-06-01 + 90d < today
    url = "https://cloud.google.com/bigquery/docs/reference/rest/v2/jobs"
    assert references.lookup(project, url) is None  # miss before add
    ref_id = references.add_reference(
        project, url, title="BQ Jobs API",
        body="jobs.query takes ...\n\n## Not extracted\n- streaming inserts\n",
        freshness="volatile", expires_after_days=90,
        sections=["cli.commands"], date=dt.date(2026, 6, 1),
    )
    assert ref_id == "ref-0001"
    hit = references.lookup(project, url)
    assert hit["id"] == "ref-0001"
    assert hit["stale"] and "expired" in hit["stale"]
    # stable never expires
    references.add_reference(
        project, "https://www.rfc-editor.org/rfc/rfc2119", title="RFC 2119",
        body="MUST/SHOULD/MAY definitions.", freshness="stable",
        date=dt.date(2020, 1, 1),
    )
    hit2 = references.lookup(project, "https://www.rfc-editor.org/rfc/rfc2119")
    assert hit2["stale"] is None


def test_ref_check_reports_expired_only_for_volatile(project):
    references.add_reference(project, "https://a.example/x", title="A",
                             body="x", freshness="volatile", date=dt.date(2026, 1, 1))
    references.add_reference(project, "https://b.example/y", title="B",
                             body="y", freshness="stable", date=dt.date(2020, 1, 1))
    findings = references.check(project)
    assert [f["reference"] for f in findings] == ["ref-0001"]


def test_ref_promote_moves_to_sources_and_keeps_resolving(project):
    ref_id = references.add_reference(
        project, "https://cloud.google.com/bigquery/quotas", title="BQ quotas",
        body="1,500 load jobs per table per day.", sections=["cli.commands"],
    )
    wf = project.workfiles_dir / "40-cli-reference.md"
    wf.write_text(wf.read_text() + f"\nLoad limits apply. <!-- ref: {ref_id} -->\n")

    src_id = references.promote(project, ref_id)
    assert src_id == "src-0001"
    spec = project.spec()
    src = spec.source_by_id(src_id)
    assert src.kind == "note" and "1,500 load jobs" in (project.root / src.path).read_text()
    assert src.relates_to == ["cli.commands"]
    # the citing workfile still resolves: reference file remains, marked promoted
    record = references.get(project, ref_id)
    assert record["promoted_to"] == src_id
    from greenhouse import state
    state.validate_project(project)


def test_add_reference_rejects_bad_section(project):
    with pytest.raises(GreenhouseError):
        references.add_reference(project, "https://x.example", title="X",
                                 body="x", sections=["nope"])
