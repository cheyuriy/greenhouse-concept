"""Commit helpers: the message is derived from session frontmatter, revisions
resolve through git, and the follow-up subject is fixed — while the commit
itself never happens inside the package."""

import datetime as dt
import subprocess

import pytest

from greenhouse import gitutil, history
from greenhouse.models import GreenhouseError

D = dt.date(2026, 9, 2)


def _session(project, **kw):
    return history.write_session(
        project, "auth-drill", date=D,
        body="Drill of auth (none → agreed).\n\nQ: x\nA: y\n",
        sections_touched=["auth", "config"], **kw,
    )


def test_commit_message_trailers_from_frontmatter(project):
    adr = history.write_decision(project, "ADC only", "why", sections=["auth"], date=D)
    sid = _session(project, decisions=[adr], ideas_raised=["idea-0001"],
                   ideas_resolved=["idea-0001", "idea-0002"])
    msg = history.commit_message(project, sid, subject="auth agreed — ADC only")
    assert msg.splitlines()[0] == "spec(demo): auth agreed — ADC only"
    assert "Sections: auth, config" in msg
    assert "Ideas: idea-0001, idea-0002" in msg  # deduped, order kept
    assert f"Decisions: {adr}" in msg
    assert msg.rstrip().endswith(f"Session: {sid}")


def test_commit_message_defaults_and_omits_empty_trailers(project):
    sid = _session(project)
    msg = history.commit_message(project, sid, trailers=["Claude-Session: https://x"])
    lines = msg.splitlines()
    assert lines[0] == "spec(demo): Drill of auth (none → agreed)."
    assert "Ideas:" not in msg and "Decisions:" not in msg
    assert lines[-1] == "Claude-Session: https://x"
    with pytest.raises(GreenhouseError):
        history.commit_message(project, sid, trailers=["not a trailer"])
    with pytest.raises(GreenhouseError):
        history.commit_message(project, "2026-01-01-nope")


def test_attach_subject_and_listings(project):
    adr = history.write_decision(project, "ADC only", "why", sections=["auth"], date=D)
    sid = _session(project, decisions=[adr])
    assert history.attach_commit_subject(project, sid) == \
        f"spec(demo): attach commit hash to session {sid}"
    history.record_commit(project, sid, "a" * 40)
    sessions = history.list_sessions(project)
    assert [s["id"] for s in sessions] == [sid]
    assert sessions[0]["commits"] == ["a" * 40] and sessions[0]["decisions"] == [adr]
    decisions = history.list_decisions(project)
    assert decisions[0]["id"] == adr and decisions[0]["commit"] == "a" * 40
    fm, body = history.read_decision(project, adr)
    assert fm["title"] == "ADC only" and "why" in body


def test_rev_parse_resolves_head_in_a_real_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    sha = gitutil.rev_parse(tmp_path, "HEAD")
    assert len(sha) == 40 and gitutil.rev_parse(tmp_path, sha) == sha
    with pytest.raises(GreenhouseError):
        gitutil.rev_parse(tmp_path, "no-such-branch")


def test_pending_decisions_resolve_for_one_run(project):
    from greenhouse import lint, state
    from greenhouse.models import ValidationFailure

    wf = project.workfiles_dir / "00-overview.md"
    wf.write_text(wf.read_text() + "\nfact <!-- why: 0001 -->\n")
    with pytest.raises(ValidationFailure):
        state.validate_project(project)
    assert any(f["rule"] == "dangling-why" for f in lint.lint_project(project))
    # the draft cites the ADR the drill is about to write
    state.validate_project(project, pending_decisions=["0001"])
    assert not any(f["rule"] == "dangling-why"
                   for f in lint.lint_project(project, pending_decisions=["0001"]))
