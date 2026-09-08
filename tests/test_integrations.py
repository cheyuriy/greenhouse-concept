from greenhouse.integrations import (
    Document,
    Exporter,
    OpenQuestionItem,
    available_exporters,
    get_exporter,
)
from greenhouse.integrations.noop import NoopExporter


def test_noop_satisfies_protocol():
    exp = NoopExporter({})
    assert isinstance(exp, Exporter)
    assert exp.health()
    r = exp.push_document("demo", Document(title="SPEC", path="final/SPEC.md", content="x"))
    assert r.ok and "final/SPEC.md" in r.detail
    r2 = exp.upsert_task("demo", OpenQuestionItem(id="q-auth-1", section="auth",
                                                  text="ADC?", blocking=True))
    assert r2.ok and "q-auth-1" in r2.detail
    assert len(exp.pushed) == 1 and len(exp.tasks) == 1


def test_noop_registered_via_entry_point(repo):
    assert "noop" in available_exporters()
    exp = get_exporter("noop", repo)
    assert exp.name == "noop"


def test_mcp_server_imports_and_declares_tools():
    from greenhouse import mcp_server

    assert mcp_server.mcp.name == "greenhouse"
