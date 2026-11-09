import json

from click.testing import CliRunner

from agent_mesh_client import state
from agent_mesh_client.cli import cli


def test_checkpoint_roundtrip_merge_and_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    assert state.load_checkpoint("agent-1") is None
    state.save_checkpoint("agent-1", task_id="t1", note="half", docs=["a.md"])
    cp = state.save_checkpoint("agent-1", note="more", docs=["a.md", "b.md"])
    assert cp["task_id"] == "t1" and cp["note"] == "more" and cp["docs"] == ["a.md", "b.md"]
    assert state.load_checkpoint("agent-1")["docs"] == ["a.md", "b.md"]
    assert state.clear_checkpoint("agent-1") is True
    assert state.load_checkpoint("agent-1") is None
    assert state.clear_checkpoint("agent-1") is False


def test_atomic_write_leaves_no_temp_and_corrupt_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    state.save_checkpoint("a/../x", task_id="t")  # unsafe id is sanitised, stays inside the dir
    cpdir = tmp_path / "checkpoints"
    assert [p.name for p in cpdir.iterdir()] == ["a_.._x.json"]
    (cpdir / "a_.._x.json").write_text("{trunc")  # simulated torn/corrupt file
    assert state.load_checkpoint("a/../x") is None


def test_record_join_stores_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    ident = {"workspace": "/w", "role": "backend", "display_name": "n", "domain": "", "project": "p"}
    state.record_join(ident, "agent-9", "http://gw")
    raw = (tmp_path / "join_state.json").read_text()
    st = json.loads(raw)["/w"]
    assert st["agent_id"] == "agent-9" and st["role"] == "backend" and st["project"] == "p"
    assert "token" not in raw.lower() and "api_key" not in raw.lower()
    assert state.get_join_state("/w")["gateway_url"] == "http://gw"


def test_cli_join_prints_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    state.save_checkpoint("agent-aaa", task_id="T7", note="resume me", docs=["draft.md"])
    ident = {"agent_id": "agent-aaa", "user_id": "u", "machine_id": "m", "workspace": "/w", "role": "r",
             "display_name": "", "domain": "", "project": "p"}
    monkeypatch.setattr("agent_mesh_client.cli.identity_mod.build_identity", lambda **kw: ident)
    monkeypatch.setattr("agent_mesh_client.cli.api.join",
                        lambda identity, capabilities: {"agent_id": "agent-aaa", "api_key": "k", "status": "ONLINE"})

    class HB:
        def __init__(self, *a): pass
        def start(self): pass

    monkeypatch.setattr("agent_mesh_client.cli.HeartbeatThread", HB)
    res = CliRunner().invoke(cli, ["join", "--role", "r", "--once"])
    assert res.exit_code == 0
    assert "T7" in res.output and "resume me" in res.output and "draft.md" in res.output


def test_poller_dedupes_orders_and_acks(tmp_path, monkeypatch):
    from agent_mesh_client import poller

    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    msgs = [
        {"message_id": "m2", "created_at": "2026-01-02", "from_agent": "a", "body": "second"},
        {"message_id": "m1", "created_at": "2026-01-01", "from_agent": "a", "body": "first"},
    ]
    acked = []
    monkeypatch.setattr(poller.api, "inbox", lambda aid, key, ack=False: list(msgs))
    monkeypatch.setattr(poller.api, "ack", lambda aid, key, ids: acked.append(ids))
    new = poller.poll_once("agent-1", "k")
    assert [m["message_id"] for m in new] == ["m1", "m2"]  # oldest first
    assert poller.poll_once("agent-1", "k") == []  # redelivery is deduplicated
    lines = state.inbox_log_file("agent-1").read_text().splitlines()
    assert len(lines) == 2 and acked[0] == ["m2", "m1"]


def test_report_queued_when_gateway_down_and_flushed(tmp_path, monkeypatch):
    import requests

    from agent_mesh_client import poller

    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr("agent_mesh_client.cli._current_identity", lambda: ("agent-1", "k"))

    def down(*a, **kw):
        raise requests.ConnectionError("dns")

    monkeypatch.setattr("agent_mesh_client.cli.api.operator_post", down)
    res = CliRunner().invoke(cli, ["status-update", "hello"])
    assert res.exit_code == 0 and "queued locally" in res.output
    assert len(state.outbox_list("agent-1")) == 1
    sent = []
    monkeypatch.setattr(poller.api, "operator_post", lambda aid, key, kind, body, title=None, task_id=None: sent.append((kind, body)))
    assert poller.flush_outbox("agent-1", "k") == 1
    assert sent == [("status", "hello")] and state.outbox_list("agent-1") == []
