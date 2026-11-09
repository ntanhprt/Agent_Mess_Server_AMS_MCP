import requests
from click.testing import CliRunner

from agent_mesh_client import api
from agent_mesh_client.cli import cli


def test_join_once_requires_role_and_registers(monkeypatch):
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", project=None, cwd=None: {
            "agent_id": "agent-aaa111",
            "user_id": "anh",
            "machine_id": "m",
            "workspace": "/w",
            "role": role,
            "display_name": display_name,
            "domain": domain,
            "project": project,
        },
    )
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.join",
        lambda identity, capabilities: {
            "agent_id": "agent-aaa111",
            "api_key": "k",
            "status": "ONLINE",
        },
    )

    started = {}

    class FakeHeartbeat:
        def __init__(self, agent_id, api_key):
            started["agent_id"] = agent_id

        def start(self):
            started["started"] = True

    monkeypatch.setattr("agent_mesh_client.cli.HeartbeatThread", FakeHeartbeat)

    result = CliRunner().invoke(cli, ["join", "--role", "backend", "--once"])

    assert result.exit_code == 0
    assert "Joined as agent-aaa111" in result.output
    assert started == {"agent_id": "agent-aaa111", "started": True}


def test_join_passes_project_option_through(monkeypatch):
    captured = {}

    def fake_build_identity(role=None, display_name="", domain="", project=None, cwd=None):
        captured["project"] = project
        return {
            "agent_id": "agent-aaa111",
            "user_id": "anh",
            "machine_id": "m",
            "workspace": "/w",
            "role": role,
            "display_name": display_name,
            "domain": domain,
            "project": project,
        }

    monkeypatch.setattr("agent_mesh_client.cli.identity_mod.build_identity", fake_build_identity)
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.join",
        lambda identity, capabilities: {
            "agent_id": "agent-aaa111",
            "api_key": "k",
            "status": "ONLINE",
        },
    )

    class FakeHeartbeat:
        def __init__(self, agent_id, api_key):
            pass

        def start(self):
            pass

    monkeypatch.setattr("agent_mesh_client.cli.HeartbeatThread", FakeHeartbeat)

    result = CliRunner().invoke(
        cli, ["join", "--role", "backend", "--project", "javis-core", "--once"]
    )

    assert result.exit_code == 0
    assert captured["project"] == "javis-core"


def test_join_without_role_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))

    def raising_build_identity(role=None, display_name="", domain="", project=None, cwd=None):
        if role is None:
            raise ValueError("No role known for workspace '/w'.")
        return {}

    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity", raising_build_identity
    )

    result = CliRunner().invoke(cli, ["join", "--once"])

    assert result.exit_code == 1
    assert "No role known" in result.output


def test_join_reports_gateway_failure_without_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", project=None, cwd=None: {
            "agent_id": "agent-aaa111",
            "user_id": "anh",
            "machine_id": "m",
            "workspace": "/w",
        },
    )

    def failing_join(identity, capabilities):
        raise api.GatewayError('{"detail":"invalid join token"}')

    monkeypatch.setattr("agent_mesh_client.cli.api.join", failing_join)

    result = CliRunner().invoke(cli, ["join", "--role", "backend", "--once"])

    assert result.exit_code == 1
    assert "Failed to join" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_join_reports_network_error_without_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", project=None, cwd=None: {
            "agent_id": "agent-aaa111",
            "user_id": "anh",
            "machine_id": "m",
            "workspace": "/w",
        },
    )

    def failing_join(identity, capabilities):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr("agent_mesh_client.cli.api.join", failing_join)

    result = CliRunner().invoke(cli, ["join", "--role", "backend", "--once"])

    assert result.exit_code == 1
    assert "Failed to join" in result.output


def test_whoami_fails_clearly_when_not_joined(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda: {
            "agent_id": "agent-zzz999",
            "user_id": "anh",
            "machine_id": "m",
            "workspace": "/w",
        },
    )

    result = CliRunner().invoke(cli, ["whoami"])

    assert result.exit_code == 1
    assert "Not joined yet" in result.output


def test_current_identity_reports_clean_error_when_no_role_known(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))

    def raising_build_identity():
        raise ValueError("No role known for workspace '/w'.")

    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity", raising_build_identity
    )

    result = CliRunner().invoke(cli, ["whoami"])

    assert result.exit_code == 1
    assert "No role known" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_status_prints_each_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda: {
            "agent_id": "agent-aaa111",
            "user_id": "anh",
            "machine_id": "m",
            "workspace": "/w",
        },
    )
    monkeypatch.setattr("agent_mesh_client.cli.config.get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.list_agents",
        lambda agent_id, api_key: [
            {"agent_id": "agent-aaa111", "status": "ONLINE", "workspace": "/w"},
            {"agent_id": "agent-bbb222", "status": "OFFLINE", "workspace": "/w2"},
        ],
    )

    result = CliRunner().invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "agent-aaa111" in result.output and "ONLINE" in result.output
    assert "agent-bbb222" in result.output and "OFFLINE" in result.output


def test_task_create_calls_api_with_options(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", cwd=None: {
            "agent_id": "agent-aaa111", "workspace": "/w",
        },
    )
    monkeypatch.setattr("agent_mesh_client.cli.config.get_api_key", lambda agent_id: "k")

    captured = {}

    def fake_create_task(agent_id, api_key, title, **kwargs):
        captured["title"] = title
        captured.update(kwargs)
        return {"task_id": "t1", "status": "READY"}

    monkeypatch.setattr("agent_mesh_client.cli.api.create_task", fake_create_task)

    result = CliRunner().invoke(
        cli, ["task", "create", "Write spec", "--required-role", "ba"]
    )

    assert result.exit_code == 0
    assert captured["title"] == "Write spec"
    assert captured["required_role"] == "ba"


def test_task_claim_reports_conflict_clearly(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", cwd=None: {
            "agent_id": "agent-aaa111", "workspace": "/w",
        },
    )
    monkeypatch.setattr("agent_mesh_client.cli.config.get_api_key", lambda agent_id: "k")

    def failing_claim(agent_id, api_key, task_id):
        raise api.GatewayError('{"detail":"task is not claimable"}')

    monkeypatch.setattr("agent_mesh_client.cli.api.claim_task", failing_claim)

    result = CliRunner().invoke(cli, ["task", "claim", "t1"])

    assert result.exit_code == 1
    assert "not claimable" in result.output or "Failed" in result.output


def _fake_identity(monkeypatch):
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", project=None, cwd=None: {
            "agent_id": "agent-aaa111", "workspace": "/w",
        },
    )
    monkeypatch.setattr("agent_mesh_client.cli.config.get_api_key", lambda agent_id: "k")


def test_report_and_status_update_post_expected_kind(monkeypatch):
    _fake_identity(monkeypatch)
    calls = []

    def fake_post(agent_id, api_key, kind, body, title=None, task_id=None):
        calls.append((kind, body, title, task_id))
        return {"event_id": "e1", "kind": kind, "status": "info"}

    monkeypatch.setattr("agent_mesh_client.cli.api.operator_post", fake_post)

    r1 = CliRunner().invoke(cli, ["report", "done", "--title", "T", "--task-id", "t1"])
    r2 = CliRunner().invoke(cli, ["status-update", "working"])

    assert r1.exit_code == 0 and "e1" in r1.output
    assert r2.exit_code == 0
    assert calls == [("report", "done", "T", "t1"), ("status", "working", None, None)]


def test_ask_without_wait_prints_event_id(monkeypatch):
    _fake_identity(monkeypatch)
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.operator_post",
        lambda *a, **k: {"event_id": "e9", "kind": "question", "status": "open"},
    )
    result = CliRunner().invoke(cli, ["ask", "which db?"])
    assert result.exit_code == 0
    assert "e9" in result.output


def test_ask_wait_polls_until_answered(monkeypatch):
    _fake_identity(monkeypatch)
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.operator_post",
        lambda *a, **k: {"event_id": "e9", "kind": "question", "status": "open"},
    )
    states = iter([
        {"status": "open"},
        {"status": "answered", "answer": "postgres", "answered_via": "web"},
    ])
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.operator_get", lambda *a, **k: next(states)
    )
    monkeypatch.setattr("agent_mesh_client.cli.time.sleep", lambda s: None)

    result = CliRunner().invoke(cli, ["ask", "which db?", "--wait", "30"])

    assert result.exit_code == 0
    assert "postgres" in result.output and "web" in result.output


def test_ask_wait_times_out_with_exit_2(monkeypatch):
    _fake_identity(monkeypatch)
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.operator_post",
        lambda *a, **k: {"event_id": "e9", "kind": "question", "status": "open"},
    )
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.operator_get", lambda *a, **k: {"status": "open"}
    )
    monkeypatch.setattr("agent_mesh_client.cli.time.sleep", lambda s: None)
    clock = iter([0.0, 0.0, 100.0, 100.0])
    monkeypatch.setattr("agent_mesh_client.cli.time.monotonic", lambda: next(clock))

    result = CliRunner().invoke(cli, ["ask", "q", "--wait", "5"])

    assert result.exit_code == 2


def test_resolve_calls_api_and_reports_conflict(monkeypatch):
    _fake_identity(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        "agent_mesh_client.cli.api.operator_resolve",
        lambda agent_id, api_key, event_id, answer: seen.update(e=event_id, a=answer) or {},
    )
    ok = CliRunner().invoke(cli, ["resolve", "e1", "yes"])
    assert ok.exit_code == 0 and seen == {"e": "e1", "a": "yes"}

    def conflict(*a, **k):
        raise api.GatewayError('{"detail":"question already answered"}')

    monkeypatch.setattr("agent_mesh_client.cli.api.operator_resolve", conflict)
    bad = CliRunner().invoke(cli, ["resolve", "e1", "no"])
    assert bad.exit_code == 1


def test_join_passes_enroll_code_option_through(monkeypatch):
    monkeypatch.setattr(
        "agent_mesh_client.cli.identity_mod.build_identity",
        lambda role=None, display_name="", domain="", project=None, cwd=None: {
            "agent_id": "agent-aaa111", "user_id": "anh", "machine_id": "m", "workspace": "/w",
        },
    )
    seen = {}

    def fake_join(identity, capabilities, enroll_code=None):
        seen["code"] = enroll_code
        return {"agent_id": "agent-planned1", "api_key": "k", "status": "ONLINE"}

    class FakeHeartbeat:
        def __init__(self, agent_id, api_key):
            pass

        def start(self):
            pass

    monkeypatch.setattr("agent_mesh_client.cli.api.join", fake_join)
    monkeypatch.setattr("agent_mesh_client.cli.HeartbeatThread", FakeHeartbeat)

    result = CliRunner().invoke(
        cli, ["join", "--role", "backend", "--enroll-code", "enr_CLI", "--once"]
    )

    assert result.exit_code == 0, result.output
    assert seen["code"] == "enr_CLI"
    assert "agent-planned1" in result.output
