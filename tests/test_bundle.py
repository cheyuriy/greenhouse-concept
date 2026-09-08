import datetime as dt
import re

import pytest

from greenhouse import bundle, history, references, sources
from greenhouse.models import GreenhouseError, LeakError


def _fill_section(text: str, heading: str, body: str) -> str:
    """Replace a scaffolded section's placeholder body (guidance comment and
    all) with real content, up to the next heading."""
    pattern = re.compile(rf"({re.escape(heading)}\n).*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    return pattern.sub(lambda m: m.group(1) + "\n" + body + "\n", text, count=1)


@pytest.fixture
def promotable(project, tmp_path):
    """Two agreed sections in one workfile with why/ref markers and an internal link."""
    pricing = tmp_path / "bq-pricing.pdf"
    pricing.write_bytes(b"%PDF-fake")
    sources.add_source(project, str(pricing), title="BQ pricing",
                       relates_to=["cli.commands"])
    references.add_reference(project, "https://cloud.google.com/bigquery/quotas",
                             title="quotas", body="1500/day")
    adr = history.write_decision(project, "sync default", "ctx", sections=["cli.commands"])

    wf = project.workfiles_dir / "40-cli-reference.md"
    text = _fill_section(
        wf.read_text(), "## Commands",
        "- **REQ-CMD-001** — `query` MUST stream results. Acceptance: large results render.\n"
        f"  <!-- why: {adr} --> <!-- ref: src-0001 §pricing, ref-0001 -->\n"
        "See [the pricing sheet](../sources/bq-pricing.pdf) for figures.\n",
    )
    text = _fill_section(text, "## Global flags and conventions",
                         "`--project` selects the GCP project.\n")
    wf.write_text(text)
    project.set_maturity("cli.global-flags", "agreed", date=dt.date(2026, 8, 20))
    project.set_maturity("cli.commands", "agreed", date=dt.date(2026, 8, 20))
    project.save()
    return project


def test_promote_strips_markers_and_internal_links(promotable):
    result = bundle.bundle(promotable)
    assert result["shards"] == ["40-cli-reference.md"]
    shard = (promotable.final_dir / "40-cli-reference.md").read_text()
    for forbidden in ("src-0001", "ref-0001", "why:", "sources/", "bq-pricing.pdf", "<!-- ref"):
        assert forbidden not in shard, forbidden
    assert "the pricing sheet" in shard          # link text survives de-linking
    assert "REQ-CMD-001" in shard                # content survives
    assert "Global flags and conventions" in shard
    spec_md = (promotable.final_dir / "SPEC.md").read_text()
    assert "## Contents" in spec_md and "REQ-CMD-001" in spec_md
    assert "src-0001" not in spec_md


def test_only_agreed_sections_promote(promotable):
    bundle.promote(promotable)
    shard = (promotable.final_dir / "40-cli-reference.md").read_text()
    assert "Output formats" not in shard  # still `none`
    assert "Errors and exit codes" not in shard


def test_toc_in_shard_order(promotable):
    # add a second promotable file that sorts earlier
    wf = promotable.workfiles_dir / "00-overview.md"
    wf.write_text(_fill_section(wf.read_text(), "## Overview and problem statement",
                                "A CLI for analysts.\n"))
    promotable.set_maturity("overview", "agreed")
    promotable.save()
    bundle.bundle(promotable)
    spec_md = (promotable.final_dir / "SPEC.md").read_text()
    assert spec_md.index("[Overview]") < spec_md.index("[CLI reference]")
    assert spec_md.splitlines()[2] == bundle.GENERATED_HEADER


def test_blocking_questions_refuse_promotion(promotable):
    promotable.add_question("auth", "ADC only?", blocking=True)
    promotable.save()
    with pytest.raises(GreenhouseError, match="q-auth-1"):
        bundle.promote(promotable)
    bundle.promote(promotable, allow_blocking=True)  # explicit override works


def test_hand_planted_leak_aborts_fail_closed(promotable):
    bundle.bundle(promotable)
    shard = promotable.final_dir / "40-cli-reference.md"
    shard.write_text(shard.read_text() + "\nBased on src-0001.\n")
    with pytest.raises(LeakError, match="src-0001"):
        bundle.bundle(promotable)
    with pytest.raises(LeakError):  # never overridable
        bundle.bundle(promotable, allow_blocking=True)


def test_rogue_final_file_with_ref_leak_aborts(promotable):
    bundle.bundle(promotable)
    (promotable.final_dir / "notes.md").write_text("see history/references/ for details\n")
    with pytest.raises(LeakError, match="history/references/"):
        bundle.bundle(promotable)
