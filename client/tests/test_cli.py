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
