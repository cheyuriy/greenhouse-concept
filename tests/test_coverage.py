import datetime as dt

from greenhouse import coverage

D1 = dt.date(2026, 8, 1)
D2 = dt.date(2026, 8, 10)
D3 = dt.date(2026, 8, 20)


def test_fresh_project_all_blanks(project):
    report = coverage.compute(project)
    assert report["histogram"] == {"none": report["total_sections"]}
    assert len(report["blanks"]) == report["total_sections"]
    assert report["stale"] == [] and report["blockers"] == []
    assert all(s["action"] == "fill" for s in report["suggestions"])


def test_blockers_ranked_by_downstream_impact(project):
    # config gates auth and security (transitively); cli.output gates nothing
    project.add_question("config", "Where does config live?", blocking=True)
    project.add_question("cli.output", "JSON always?", blocking=True)
    report = coverage.compute(project)
    assert [b["section"] for b in report["blockers"]][0] == "config"
    top = report["blockers"][0]
    assert set(top["unblocks"]) >= {"auth", "security"}
    assert top["impact"] >= 2


def test_staleness_when_dependency_moves_after_agreement(project):
    project.set_maturity("config", "agreed", date=D1)
    project.set_maturity("auth", "agreed", date=D2)
    project.touch("config", date=D3)  # config changes after auth agreed
    project.save()
    report = coverage.compute(project)
    stale = [s for s in report["stale"] if s["section"] == "auth"]
    assert stale and stale[0]["dependency"] == "config"
    # and re-review outranks everything else
    assert report["suggestions"][0] == {
        "action": "re-review",
        "section": "auth",
        "reason": "agreed but stale (dependency-changed)",
        "score": 90,
    }


def test_no_staleness_when_agreement_is_newer(project):
    project.touch("config", date=D1)
    project.set_maturity("auth", "agreed", date=D2)
    project.save()
    assert coverage.compute(project)["stale"] == []


def test_assumptions_inventory(project):
    project.add_assumption("auth", "Analysts have gcloud installed")
    project.save()
    report = coverage.compute(project)
    assert report["assumptions"] == [
        {"section": "auth", "text": "Analysts have gcloud installed"}
    ]
