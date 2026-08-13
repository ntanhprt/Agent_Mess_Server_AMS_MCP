import os
import stat

import responses

from agent_mesh_client import api, config

IDENTITY = {
    "user_id": "anh",
    "machine_id": "DEV-PC-01",
    "workspace": "/home/anh/proj",
    "agent_id": "agent-aaa111",
}


@responses.activate
def test_join_saves_returned_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-aaa111", "api_key": "secret-key", "status": "ONLINE"},
        status=200,
    )

    result = api.join(IDENTITY, capabilities=["python"])

    assert result["api_key"] == "secret-key"
    assert config.get_api_key("agent-aaa111") == "secret-key"
    # The join request must carry the shared join token.
    assert responses.calls[0].request.headers["X-Join-Token"] == config.join_token()


@responses.activate
def test_join_sends_configured_join_token(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_MESH_JOIN_TOKEN", "prod-token-xyz")
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-aaa111", "api_key": "secret-key", "status": "ONLINE"},
        status=200,
    )

    api.join(IDENTITY, capabilities=[])

    assert responses.calls[0].request.headers["X-Join-Token"] == "prod-token-xyz"


@responses.activate
def test_join_writes_credentials_file_with_owner_only_permissions(monkeypatch, tmp_path):
    cred_home = tmp_path / "mesh-home"
    monkeypatch.setenv("AGENT_MESH_HOME", str(cred_home))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-aaa111", "api_key": "secret-key", "status": "ONLINE"},
        status=200,
    )

    api.join(IDENTITY, capabilities=[])

    cred_file = cred_home / "credentials.json"
    assert cred_file.exists()
    assert stat.S_IMODE(os.stat(cred_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(cred_home).st_mode) == 0o700


@responses.activate
def test_get_agent_returns_agent_details(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.GET,
        f"{config.gateway_url()}/agents/agent-bbb222",
        json={"agent_id": "agent-bbb222", "status": "OFFLINE", "workspace": "/home/anh/b"},
        status=200,
    )

    result = api.get_agent("agent-bbb222", "key-a")

    assert result["agent_id"] == "agent-bbb222"
    assert result["status"] == "OFFLINE"
    assert responses.calls[0].request.headers["Authorization"] == "Bearer key-a"


@responses.activate
def test_get_agent_raises_for_unknown_agent(monkeypatch, tmp_path):
    import requests

    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.GET,
        f"{config.gateway_url()}/agents/agent-zzz999",
        json={"detail": "agent not found"},
        status=404,
    )

    raised = False
    try:
        api.get_agent("agent-zzz999", "key-a")
    except requests.HTTPError:
        raised = True
    assert raised


@responses.activate
def test_heartbeat_raises_on_error_status(monkeypatch, tmp_path):
    import requests

    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/heartbeat",
        json={"detail": "Invalid API key"},
        status=401,
    )

    raised = False
    try:
        api.heartbeat("agent-aaa111", "stale-key")
    except requests.HTTPError:
        raised = True
    assert raised


@responses.activate
def test_join_raises_gateway_error_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"detail": "boom"},
        status=401,
    )

    raised = False
    try:
        api.join(IDENTITY, capabilities=[])
    except api.GatewayError:
        raised = True
    assert raised


@responses.activate
def test_send_message_and_inbox_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/messages",
        json={
            "message_id": "m1",
            "from_agent": "agent-aaa111",
            "to_agent": "agent-bbb222",
            "body": "hi",
            "status": "pending",
            "created_at": "2026-08-12T00:00:00",
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{config.gateway_url()}/messages/inbox",
        json=[
            {
                "message_id": "m1",
                "from_agent": "agent-aaa111",
                "to_agent": "agent-bbb222",
                "body": "hi",
                "status": "delivered",
                "created_at": "2026-08-12T00:00:00",
            }
        ],
        status=200,
    )

    sent = api.send_message("agent-aaa111", "key-a", "agent-bbb222", "hi")
    assert sent["message_id"] == "m1"

    received = api.inbox("agent-bbb222", "key-b")
    assert received[0]["body"] == "hi"


@responses.activate
def test_create_task_posts_to_tasks_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/tasks",
        json={
            "task_id": "t1", "project": "/w", "title": "T1", "description": None,
            "created_by": "agent-a", "required_role": "backend", "assigned_to": None,
            "status": "READY", "priority": "normal", "input_ref": None, "artifact_ref": None,
            "depends_on": [], "created_at": "2026-08-13T00:00:00", "updated_at": "2026-08-13T00:00:00",
        },
        status=200,
    )

    result = api.create_task("agent-a", "key-a", "T1", required_role="backend")

    assert result["task_id"] == "t1"
    sent_body = responses.calls[0].request.body
    assert b'"required_role": "backend"' in sent_body or b'"required_role":"backend"' in sent_body


@responses.activate
def test_claim_task_posts_to_claim_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/tasks/t1/claim",
        json={"task_id": "t1", "status": "CLAIMED", "assigned_to": "agent-a"},
        status=200,
    )

    result = api.claim_task("agent-a", "key-a", "t1")

    assert result["status"] == "CLAIMED"


@responses.activate
def test_list_tasks_sends_project_as_query_param_when_provided(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.GET,
        f"{config.gateway_url()}/tasks",
        json=[],
        status=200,
    )

    api.list_tasks("agent-a", "key-a", project="javis-core")

    assert responses.calls[0].request.params["project"] == "javis-core"


@responses.activate
def test_claim_task_raises_gateway_error_on_conflict(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/tasks/t1/claim",
        json={"detail": "task is not claimable"},
        status=409,
    )

    raised = False
    try:
        api.claim_task("agent-a", "key-a", "t1")
    except api.GatewayError:
        raised = True
    assert raised
