import json

import pytest
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


@responses.activate
def test_operator_post_get_resolve_roundtrip():
    base = config.gateway_url()
    responses.add(
        responses.POST, f"{base}/operator/events",
        json={"event_id": "e1", "kind": "question", "status": "open", "created_at": "x"},
    )
    responses.add(
        responses.GET, f"{base}/operator/events/e1",
        json={"event_id": "e1", "status": "open", "answer": None},
    )
    responses.add(
        responses.POST, f"{base}/operator/events/e1/resolve",
        json={"event_id": "e1", "status": "answered", "answered_via": "cli"},
    )

    created = api.operator_post("agent-aaa111", "k", "question", "which db?", title="DB")
    assert created["event_id"] == "e1"
    sent = json.loads(responses.calls[0].request.body)
    assert sent == {"kind": "question", "body": "which db?", "title": "DB", "task_id": None}
    assert responses.calls[0].request.headers["Authorization"] == "Bearer k"

    assert api.operator_get("agent-aaa111", "k", "e1")["status"] == "open"
    assert api.operator_resolve("agent-aaa111", "k", "e1", "pg")["answered_via"] == "cli"
    assert json.loads(responses.calls[2].request.body) == {"answer": "pg"}


@responses.activate
def test_operator_resolve_raises_gateway_error_on_409():
    responses.add(
        responses.POST, f"{config.gateway_url()}/operator/events/e1/resolve",
        json={"detail": "question already answered"}, status=409,
    )
    with pytest.raises(api.GatewayError):
        api.operator_resolve("agent-aaa111", "k", "e1", "pg")


def test_agent_context_and_message_origin_and_ack(monkeypatch):
    from agent_mesh_client import api

    calls = []

    class Resp:
        def __init__(self, status=200, data=None):
            self.status_code, self._d, self.text = status, data or {}, "x"

        def json(self):
            return self._d

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url))
        return Resp(404) if url.endswith("/nope") else Resp(200, {"url": url})

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json))
        return Resp(200, {})

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(api.requests, "post", fake_post)
    monkeypatch.setattr(api.config, "gateway_url", lambda: "http://gw")

    assert api.agent_context("a", "k")["url"] == "http://gw/agents/me/context"
    assert api.message_origin("a", "k", "m1")["url"] == "http://gw/agents/me/messages/m1"
    import pytest
    with pytest.raises(api.GatewayError):
        api.message_origin("a", "k", "nope")
    api.operator_post("a", "k", "status", "b")
    api.operator_post("a", "k", "status", "b", ack="bc-1")
    assert "ack" not in calls[-2][2] and calls[-1][2]["ack"] == "bc-1"


# ---------------------------------------------------------------- enrollment


@responses.activate
def test_join_sends_enrollment_code_from_env_and_saves_issued_id_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_MESH_ENROLL_CODE", "enr_TESTCODE")
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-planned1", "api_key": "k1", "status": "ONLINE"},
        status=200,
    )

    result = api.join(IDENTITY, capabilities=[])

    assert responses.calls[0].request.headers["X-Enrollment-Token"] == "enr_TESTCODE"
    assert responses.calls[0].request.headers["X-Join-Token"] == config.join_token()  # unchanged
    assert result["agent_id"] == "agent-planned1"
    assert config.get_api_key("agent-planned1") == "k1"
    assert config.resolve_agent_id("agent-aaa111") == "agent-planned1"


@responses.activate
def test_join_explicit_enroll_code_overrides_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_MESH_ENROLL_CODE", "enr_FROMENV")
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-aaa111", "api_key": "k", "status": "ONLINE"},
        status=200,
    )
    api.join(IDENTITY, capabilities=[], enroll_code="enr_EXPLICIT")
    assert responses.calls[0].request.headers["X-Enrollment-Token"] == "enr_EXPLICIT"


@responses.activate
def test_join_without_code_sends_no_enrollment_header(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_MESH_ENROLL_CODE", raising=False)
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-aaa111", "api_key": "k", "status": "ONLINE"},
        status=200,
    )
    api.join(IDENTITY, capabilities=[])
    assert "X-Enrollment-Token" not in responses.calls[0].request.headers


@responses.activate
def test_rejoin_after_enrollment_uses_issued_id_and_key_not_the_spent_code(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_MESH_ENROLL_CODE", "enr_ONCE")
    responses.add(
        responses.POST,
        f"{config.gateway_url()}/agents/join",
        json={"agent_id": "agent-planned1", "api_key": "k1", "status": "ONLINE"},
        status=200,
    )
    api.join(IDENTITY, capabilities=[])
    api.join(IDENTITY, capabilities=[])  # env var still set, but a credential now exists

    second = responses.calls[1].request
    assert "X-Enrollment-Token" not in second.headers
    body = json.loads(second.body)
    assert body["agent_id"] == "agent-planned1" and body["api_key"] == "k1"
