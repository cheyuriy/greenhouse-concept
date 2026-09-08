import json

from typer.testing import CliRunner

from greenhouse import dashboard, history, state
from greenhouse.cli import app

runner = CliRunner()


def test_configure_trello_roundtrips_and_validates(project):
    project.configure_trello(board="Demo Board", enabled=True)
    project.save()
    reloaded = state.Project(project.root)
    cfg = reloaded.spec().trello
    assert cfg is not None and cfg.enabled and cfg.board == "Demo Board"
    assert cfg.board_url is None
    # the block sits with the header, not after the section list
    keys = list(reloaded.data.keys())
    assert keys.index("trello") < keys.index("sections")
    state.validate_project(reloaded)


def test_configure_trello_refuses_enabling_without_board(project):
    import pytest

    from greenhouse.models import GreenhouseError

    with pytest.raises(GreenhouseError):
        project.configure_trello(enabled=True)


def test_configure_trello_partial_updates_keep_other_fields(project):
    project.configure_trello(board="Demo Board", enabled=True)
    project.configure_trello(board_url="https://trello.com/b/abc/demo")
    node = project.configure_trello(enabled=False)
    assert node["board"] == "Demo Board"
    assert node["board_url"] == "https://trello.com/b/abc/demo"
    assert node["enabled"] is False


def test_plan_has_lists_status_and_one_card_per_id(project):
    spec = project.spec()
    first = spec.sections[0].id
    qid = project.add_question(first, "Which auth flow?", blocking=True)
    project.set_maturity(first, "draft")
    project.save()
    report = dashboard.plan(project)

    assert report["lists"][0] == dashboard.LIST_STATUS
    assert dashboard.section_list("agreed") in report["lists"]
    ids = [c["id"] for c in report["cards"]]
    assert len(ids) == len(set(ids)), "one card per id"
    assert "status" in ids and qid in ids and first in ids
    by_id = {c["id"]: c for c in report["cards"]}
    assert by_id[qid]["list"] == dashboard.LIST_BLOCKING
    assert by_id[qid]["kind"] == "question"
    assert by_id[qid]["name"].startswith(f"[{qid}] ⛔ Which auth flow?")
    assert by_id[first]["list"] == dashboard.section_list("draft")
    assert "⛔ 1 blocking" in by_id[first]["name"]
    assert by_id[first]["desc"].endswith(f"greenhouse: demo / {first}")
    # every section in the taxonomy is mirrored
    assert {s.id for s in spec.sections} <= set(ids)
    assert report["enabled"] is False and report["board"] is None


def test_plan_moves_resolved_question_to_answered(project):
    first = project.spec().sections[0].id
    qid = project.add_question(first, "Which auth flow?")
    project.save()
    history.write_session(project, "auth", "Q: Which auth flow?\nA: ADC",
                          sections_touched=[first], questions_resolved=[qid])
    project.resolve_question(qid)
    project.save()
    by_id = {c["id"]: c for c in dashboard.plan(project)["cards"]}
    assert by_id[qid]["list"] == dashboard.LIST_ANSWERED
    assert by_id[qid]["preserve_name"] is True
    assert "auth" in by_id[qid]["desc"]


def test_plan_card_limits_and_id_parsing(project):
    first = project.spec().sections[0].id
    project.add_assumption(first, "x" * 5000)
    project.save()
    for card in dashboard.plan(project)["cards"]:
        assert len(card["name"]) <= dashboard.NAME_MAX
        assert len(card["desc"]) <= dashboard.DESC_MAX
        assert dashboard.card_id_from_name(card["name"]) == card["id"]
    assert dashboard.card_id_from_name("no marker here") is None
    assert dashboard.card_kind("q-auth-1") == "question"
    assert dashboard.card_kind("idea-0001") == "idea"
    assert dashboard.card_kind("cli.commands") == "section"
    assert dashboard.RETIRE_TO["question"] == dashboard.LIST_ANSWERED


def test_cli_trello_configure_show_plan(project, monkeypatch):
    monkeypatch.chdir(project.root)
    r = runner.invoke(app, ["trello", "show"])
    assert r.exit_code == 3
    r = runner.invoke(app, ["trello", "configure", "--board", "Demo Board", "--enable"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["trello", "show", "--json"])
    assert r.exit_code == 0 and json.loads(r.stdout)["board"] == "Demo Board"
    r = runner.invoke(app, ["trello", "plan", "--json"])
    assert r.exit_code == 0, r.output
    report = json.loads(r.stdout)
    assert report["enabled"] is True and report["board"] == "Demo Board"
    assert any(c["id"] == "status" for c in report["cards"])
    r = runner.invoke(app, ["trello", "configure"])
    assert r.exit_code == 1
