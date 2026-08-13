import requests

from agent_mesh_mcp import server

IDENTITY = {
    "agent_id": "agent-aaa111",
    "user_id": "anh",
    "machine_id": "m",
    "workspace": "/w",
}


def _call(tool, *args, **kwargs):
    # The installed `mcp` SDK version may return the plain function from
    # @mcp.tool() (callable directly) or a Tool wrapper exposing `.fn`.
    target = getattr(tool, "fn", tool)
    return target(*args, **kwargs)


class FakeHeartbeat:
    def __init__(self, agent_id, api_key):
        pass

    def start(self):
        pass


def test_agent_whoami_joins_then_returns_identity(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", None)
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: None)
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))
    monkeypatch.setattr(
        server.api,
        "join",
        lambda identity, capabilities: {"agent_id": "agent-aaa111", "api_key": "k", "status": "ONLINE"},
    )
    monkeypatch.setattr(
        server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id, "status": "ONLINE"}
    )
    monkeypatch.setattr(server, "HeartbeatThread", FakeHeartbeat)

    result = _call(server.agent_whoami)

    assert result == {"agent_id": "agent-aaa111", "status": "ONLINE"}


def test_agent_whoami_reuses_cached_key_without_rejoining(monkeypatch):
    """The cached-key fast path stays in place for every tool except agent_join."""
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "cached-key")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

    joins = []

    def recording_join(identity, capabilities):
        joins.append(identity)
        return {"agent_id": "agent-aaa111", "api_key": "fresh-key", "status": "ONLINE"}

    monkeypatch.setattr(server.api, "join", recording_join)
    monkeypatch.setattr(
        server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id, "api_key": api_key}
    )

    result = _call(server.agent_whoami)

    assert joins == []
    assert result["api_key"] == "cached-key"


def test_agent_join_rejoins_even_when_local_key_exists(monkeypatch):
    """agent_join must always re-register so it self-heals after a Gateway reset."""

    class StaleHeartbeat:
        stopped = False

        def stop(self):
            StaleHeartbeat.stopped = True

    monkeypatch.setattr(server, "_heartbeat", StaleHeartbeat())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "stale-key")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda role=None, display_name="", domain="", project=None, cwd=None: dict(IDENTITY))

    joins = []

    def recording_join(identity, capabilities):
        joins.append(identity)
        return {"agent_id": "agent-aaa111", "api_key": "fresh-key", "status": "ONLINE"}

    monkeypatch.setattr(server.api, "join", recording_join)
    monkeypatch.setattr(
        server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id, "api_key": api_key}
    )

    restarted = {}

    class RecordingHeartbeat:
        def __init__(self, agent_id, api_key):
            restarted["api_key"] = api_key

        def start(self):
            restarted["started"] = True

    monkeypatch.setattr(server, "HeartbeatThread", RecordingHeartbeat)

    result = _call(server.agent_join, role="backend")

    assert len(joins) == 1
    # The freshly issued key is used, not the stale cached one.
    assert result["api_key"] == "fresh-key"
    # The old heartbeat (still holding the stale key) is replaced, otherwise the
    # agent would stay OFFLINE despite having re-registered successfully.
    assert StaleHeartbeat.stopped is True
    assert restarted == {"api_key": "fresh-key", "started": True}


def test_agent_join_starts_heartbeat_when_not_running(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", None)
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: None)
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda role=None, display_name="", domain="", project=None, cwd=None: dict(IDENTITY))
    monkeypatch.setattr(
        server.api,
        "join",
        lambda identity, capabilities: {"agent_id": "agent-aaa111", "api_key": "k", "status": "ONLINE"},
    )
    monkeypatch.setattr(
        server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id, "status": "ONLINE"}
    )

    started = {}

    class RecordingHeartbeat:
        def __init__(self, agent_id, api_key):
            started["agent_id"] = agent_id

        def start(self):
            started["started"] = True

    monkeypatch.setattr(server, "HeartbeatThread", RecordingHeartbeat)

    _call(server.agent_join, role="backend")

    assert started == {"agent_id": "agent-aaa111", "started": True}


def test_agent_get_fetches_agent_directly(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

    requested = {}

    def fake_get_agent(agent_id, api_key):
        requested["agent_id"] = agent_id
        requested["api_key"] = api_key
        return {"agent_id": agent_id, "status": "OFFLINE"}

    monkeypatch.setattr(server.api, "get_agent", fake_get_agent)

    result = _call(server.agent_get, "agent-bbb222")

    assert result == {"agent_id": "agent-bbb222", "status": "OFFLINE"}
    assert requested == {"agent_id": "agent-bbb222", "api_key": "k"}


def test_agent_get_returns_error_for_unknown_agent(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

    def not_found(agent_id, api_key):
        raise requests.HTTPError("404 Client Error: Not Found")

    monkeypatch.setattr(server.api, "get_agent", not_found)

    result = _call(server.agent_get, "agent-zzz999")

    assert result == {"error": "agent agent-zzz999 not found"}


def test_agent_join_requires_role(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", None)
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: None)

    import pytest

    with pytest.raises(TypeError):
        _call(server.agent_join)


def test_agent_join_passes_role_through_to_build_identity(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", None)
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: None)

    captured = {}

    def recording_build_identity(role=None, display_name="", domain="", project=None, cwd=None):
        captured["role"] = role
        captured["display_name"] = display_name
        captured["domain"] = domain
        captured["project"] = project
        return {**IDENTITY, "role": role, "display_name": display_name, "domain": domain, "project": project}

    monkeypatch.setattr(server.identity_mod, "build_identity", recording_build_identity)
    monkeypatch.setattr(
        server.api,
        "join",
        lambda identity, capabilities: {"agent_id": "agent-aaa111", "api_key": "k", "status": "ONLINE"},
    )
    monkeypatch.setattr(
        server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id, "status": "ONLINE"}
    )
    monkeypatch.setattr(server, "HeartbeatThread", FakeHeartbeat)

    _call(server.agent_join, role="backend", display_name="BE-01", domain="auth")

    assert captured == {"role": "backend", "display_name": "BE-01", "domain": "auth", "project": None}


def test_agent_join_passes_project_through(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", None)
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: None)

    captured = {}

    def recording_build_identity(role=None, display_name="", domain="", project=None, cwd=None):
        captured["project"] = project
        return {**IDENTITY, "role": role, "display_name": display_name, "domain": domain, "project": project}

    monkeypatch.setattr(server.identity_mod, "build_identity", recording_build_identity)
    monkeypatch.setattr(
        server.api,
        "join",
        lambda identity, capabilities: {"agent_id": "agent-aaa111", "api_key": "k", "status": "ONLINE"},
    )
    monkeypatch.setattr(
        server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id, "status": "ONLINE"}
    )
    monkeypatch.setattr(server, "HeartbeatThread", FakeHeartbeat)

    _call(server.agent_join, role="backend", project="javis-core")

    assert captured["project"] == "javis-core"


def test_task_create_delegates_to_api(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

    captured = {}

    def fake_create_task(agent_id, api_key, title, **kwargs):
        captured["title"] = title
        captured.update(kwargs)
        return {"task_id": "t1", "status": "READY"}

    monkeypatch.setattr(server.api, "create_task", fake_create_task)

    result = _call(server.task_create, "Write spec", required_role="ba")

    assert result == {"task_id": "t1", "status": "READY"}
    assert captured["title"] == "Write spec"
    assert captured["required_role"] == "ba"


def test_task_list_defaults_to_ready_and_filters_by_own_role(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(
        server.identity_mod, "build_identity", lambda: {**IDENTITY, "role": "backend"}
    )

    def fake_list_tasks(agent_id, api_key, status=None, required_role=None, project=None):
        assert status == "READY"
        assert required_role is None
        return [
            {"task_id": "t1", "required_role": "backend", "title": "for me"},
            {"task_id": "t2", "required_role": "frontend", "title": "not for me"},
            {"task_id": "t3", "required_role": None, "title": "anyone"},
        ]

    monkeypatch.setattr(server.api, "list_tasks", fake_list_tasks)

    result = _call(server.task_list)

    assert {t["task_id"] for t in result} == {"t1", "t3"}


def test_task_list_with_explicit_required_role_skips_filtering(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(
        server.identity_mod, "build_identity", lambda: {**IDENTITY, "role": "backend"}
    )

    captured_calls = []

    def fake_list_tasks(agent_id, api_key, status=None, required_role=None, project=None):
        captured_calls.append({"status": status, "required_role": required_role, "project": project})
        return [
            {"task_id": "t1", "required_role": "frontend", "title": "frontend only"},
            {"task_id": "t2", "required_role": None, "title": "anyone"},
        ]

    monkeypatch.setattr(server.api, "list_tasks", fake_list_tasks)

    result = _call(server.task_list, required_role="frontend")

    # Result should be returned unchanged, including t1 (frontend role),
    # NOT filtered to caller's own role (backend).
    assert {t["task_id"] for t in result} == {"t1", "t2"}
    # Verify the explicit required_role was passed through to the API.
    assert captured_calls == [{"status": "READY", "required_role": "frontend", "project": None}]


def test_task_create_passes_project_through(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

    captured = {}

    def fake_create_task(agent_id, api_key, title, **kwargs):
        captured.update(kwargs)
        return {"task_id": "t1", "status": "READY"}

    monkeypatch.setattr(server.api, "create_task", fake_create_task)

    _call(server.task_create, "Write spec", project="javis-core")

    assert captured["project"] == "javis-core"


def test_task_list_passes_project_through(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(
        server.identity_mod, "build_identity", lambda: {**IDENTITY, "role": "backend"}
    )

    captured_calls = []

    def fake_list_tasks(agent_id, api_key, status=None, required_role=None, project=None):
        captured_calls.append({"status": status, "project": project})
        return [{"task_id": "t1", "required_role": None, "title": "anyone"}]

    monkeypatch.setattr(server.api, "list_tasks", fake_list_tasks)

    result = _call(server.task_list, project="javis-core")

    assert {t["task_id"] for t in result} == {"t1"}
    assert captured_calls == [{"status": "READY", "project": "javis-core"}]


def test_task_claim_delegates_to_api(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))
    monkeypatch.setattr(
        server.api, "claim_task", lambda agent_id, api_key, task_id: {"task_id": task_id, "status": "CLAIMED"}
    )

    result = _call(server.task_claim, "t1")

    assert result == {"task_id": "t1", "status": "CLAIMED"}


def test_task_complete_delegates_to_api(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

    captured = {}

    def fake_complete_task(agent_id, api_key, task_id, summary, artifact_ref=None):
        captured.update(task_id=task_id, summary=summary, artifact_ref=artifact_ref)
        return {"task_id": task_id, "status": "DONE"}

    monkeypatch.setattr(server.api, "complete_task", fake_complete_task)

    result = _call(server.task_complete, "t1", "done", artifact_ref="agent-mesh/t1/out.md")

    assert result == {"task_id": "t1", "status": "DONE"}
    assert captured == {"task_id": "t1", "summary": "done", "artifact_ref": "agent-mesh/t1/out.md"}


def test_task_upload_artifact_delegates_to_artifacts_module(monkeypatch, tmp_path):
    src = tmp_path / "spec.md"
    src.write_text("hello")

    monkeypatch.setattr(server.artifacts, "upload_artifact", lambda path, task_id: f"{task_id}/spec.md")

    result = _call(server.task_upload_artifact, str(src), "t1")

    assert result == "t1/spec.md"


def test_task_download_artifact_delegates_to_artifacts_module(monkeypatch):
    called = {}
    monkeypatch.setattr(
        server.artifacts,
        "download_artifact",
        lambda object_key, dest_path: called.update(object_key=object_key, dest_path=dest_path),
    )

    _call(server.task_download_artifact, "t1/spec.md", "/tmp/out.md")

    assert called == {"object_key": "t1/spec.md", "dest_path": "/tmp/out.md"}
