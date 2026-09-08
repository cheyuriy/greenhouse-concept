"""The canonical traceability fixture: 3 sessions, 2 ADRs (one superseding
the other), 4 ideas (2 rejected) over one section — trace returns all of it
chronologically, rejection reasons intact, and survives an alias rename."""

import datetime as dt

import pytest

from greenhouse import history, ideas, state, trace
from greenhouse.models import ValidationFailure

D = [dt.date(2026, 8, d) for d in (1, 5, 10, 15, 20)]
SECTION = "cli.commands"


@pytest.fixture
def storied(project):
    p = project
    # ideas: 4 relating to the section, 2 later rejected
    ideas.add_idea(p, "Dry-run cost estimate before every query",
                   relates_to=[SECTION], source="idea-scout", date=D[0])
    ideas.add_idea(p, "Interactive schema browser for datasets",
                   relates_to=[SECTION], source="user", date=D[0])
    ideas.add_idea(p, "Automatic result caching layer",
                   relates_to=[SECTION], source="idea-scout", date=D[1])
    ideas.add_idea(p, "Query templates with parameter substitution",
                   relates_to=[SECTION], source="drill", date=D[1])
    ideas.set_status(p, "idea-0002", "rejected", resolution="a TUI is out of scope", date=D[2])
    ideas.set_status(p, "idea-0003", "rejected", resolution="premature optimisation", date=D[2])

    # session 1: exploration, questions asked
    q1 = p.add_question(SECTION, "Should query run synchronously by default?",
                        blocking=True, date=D[1])
    history.write_session(
        p, "explore-query-command", date=D[1],
        body=f"### {q1}\n**Q:** Sync by default?\n**A (user):** undecided yet.\n",
        sections_touched=[SECTION], questions_asked=[q1],
        maturity_transitions=[{"section": SECTION, "from": "none", "to": "stub"}],
    )
    p.set_maturity(SECTION, "stub", date=D[1])
    p.save()

    # session 2: decision 0001 resolves q1
    p.resolve_question(q1)
    adr1 = history.write_decision(
        p, "query runs synchronously by default", date=D[2],
        body="## Context\nAnalysts want immediate feedback.\n## Choice\nSync default, --async flag.\n",
        sections=[SECTION], ideas=["idea-0001"], questions_resolved=[q1],
        session=None,
    )
    history.write_session(
        p, "decide-sync-default", date=D[2],
        body=f"### {q1}\n**Q:** Sync by default?\n**A (user):** yes, with an --async escape hatch.\n",
        sections_touched=[SECTION], questions_resolved=[q1], decisions=[adr1],
        maturity_transitions=[{"section": SECTION, "from": "stub", "to": "draft"}],
    )
    p.set_maturity(SECTION, "draft", date=D[2])
    p.save()

    # session 3: ADR 0002 supersedes 0001
    adr2 = history.write_decision(
        p, "query streams results asynchronously by default", date=D[4],
        body="## Context\nLarge results froze terminals.\n## Choice\nAsync stream, --wait flag.\n",
        sections=[SECTION], supersedes=[adr1],
    )
    history.write_session(
        p, "revisit-sync-decision", date=D[4],
        body="**Q:** Keep sync default given the freeze reports?\n**A (user):** no — flip it.\n",
        sections_touched=[SECTION], decisions=[adr2],
        maturity_transitions=[{"section": SECTION, "from": "draft", "to": "agreed"}],
    )
    p.set_maturity(SECTION, "agreed", date=D[4])
    p.save()
    return p


def test_trace_reconstructs_everything_chronologically(storied):
    result = trace.trace(storied, SECTION)
    events = result["events"]
    dates = [e["date"] for e in events if e["date"]]
    assert dates == sorted(dates), "chronological order"

    by_kind = {}
    for e in events:
        by_kind.setdefault(e["kind"], []).append(e)
    assert len(by_kind["session"]) == 3
    assert len(by_kind["decision"]) == 2
    assert len(by_kind["idea"]) == 4

    # rejection reasons intact
    rejected = [e for e in by_kind["idea"] if e.get("status") == "rejected"]
    assert {"a TUI is out of scope", "premature optimisation"} == {
        e["resolution"] for e in rejected
    }
    # supersede chain visible
    adr2 = next(e for e in by_kind["decision"] if e["id"] == "0002")
    assert adr2["supersedes"] == ["0001"]
    adr1 = next(e for e in by_kind["decision"] if e["id"] == "0001")
    assert adr1["superseded_by"] == "0002"
    # maturity transitions recorded
    transitions = [t for e in by_kind["session"] for t in e["transitions"]]
    assert any("none → stub" in t for t in transitions)
    assert any("draft → agreed" in t for t in transitions)


def test_trace_context_carries_verbatim_answers(storied):
    md = trace.render_markdown(trace.trace(storied, SECTION), context=True)
    assert "with an --async escape hatch" in md  # the user's words, not a paraphrase
    assert "## Current text" in md


def test_trace_survives_alias_rename(storied):
    sec = storied.raw_section(SECTION)
    sec["id"] = "cli.query-commands"
    sec["aliases"] = [SECTION]
    storied.save()
    result = trace.trace(storied, SECTION)  # old id still resolves
    assert len([e for e in result["events"] if e["kind"] == "session"]) == 3
    result2 = trace.trace(storied, "cli.query-commands")  # and the new one
    assert len([e for e in result2["events"] if e["kind"] == "session"]) == 3


def test_trace_adr_shows_supersession(storied):
    result = trace.trace(storied, "0001")
    assert result["current"]["status"] == "superseded"
    assert result["current"]["superseded_by"] == "0002"


def test_trace_idea_includes_sessions_and_decisions(storied):
    result = trace.trace(storied, "idea-0001")
    kinds = {e["kind"] for e in result["events"]}
    assert "decision" in kinds  # ADR 0001 weighed idea-0001


def test_validate_fails_on_dangling_history_ids(storied):
    history.write_session(
        storied, "broken", date=D[4],
        body="x", sections_touched=[], ideas_raised=["idea-9999"],
    )
    with pytest.raises(ValidationFailure) as exc:
        state.validate_project(storied)
    assert any("idea-9999" in p for p in exc.value.problems)


def test_validate_fails_on_dangling_why_marker(storied):
    wf = storied.workfiles_dir / "40-cli-reference.md"
    wf.write_text(wf.read_text() + "\n- **REQ-QUERY-001** — MUST stream. <!-- why: 0009 -->\n")
    with pytest.raises(ValidationFailure) as exc:
        state.validate_project(storied)
    assert any("0009" in p for p in exc.value.problems)


def test_index_regenerated(storied):
    index = (storied.history_dir / "INDEX.md").read_text()
    assert "| 2026-08-10 | session |" in index
    assert "0002" in index and "[superseded]" in index
