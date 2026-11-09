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


def _joined(monkeypatch):
    monkeypatch.setattr(server, "_heartbeat", object())
    monkeypatch.setattr(server.config, "get_api_key", lambda agent_id: "k")
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))


def test_operator_report_status_ask_post_expected_kinds(monkeypatch):
    _joined(monkeypatch)
    calls = []

    def fake_post(agent_id, api_key, kind, body, title=None, task_id=None):
        calls.append((agent_id, kind, body, title, task_id))
        return {"event_id": "e1", "kind": kind}

    monkeypatch.setattr(server.api, "operator_post", fake_post)

    _call(server.operator_report, "done", title="T", task_id="t1")
    _call(server.operator_status, "working")
    result = _call(server.operator_ask, "which db?")

    assert result == {"event_id": "e1", "kind": "question"}
    assert calls == [
        ("agent-aaa111", "report", "done", "T", "t1"),
        ("agent-aaa111", "status", "working", None, None),
        ("agent-aaa111", "question", "which db?", None, None),
    ]


def test_operator_ask_description_tells_model_to_ask_in_cli_too():
    doc = server.operator_ask.__doc__ if callable(server.operator_ask) else server.operator_ask.fn.__doc__
    assert "CLI" in doc and "FIRST" in doc


def test_operator_check_answer_and_resolve_delegate_to_api(monkeypatch):
    _joined(monkeypatch)
    monkeypatch.setattr(
        server.api, "operator_get",
        lambda agent_id, api_key, event_id: {"event_id": event_id, "status": "open"},
    )
    monkeypatch.setattr(
        server.api, "operator_resolve",
        lambda agent_id, api_key, event_id, answer: {"event_id": event_id, "answer": answer, "answered_via": "cli"},
    )

    assert _call(server.operator_check_answer, "e1") == {"event_id": "e1", "status": "open"}
    assert _call(server.operator_resolve, "e1", "pg")["answered_via"] == "cli"


def test_agent_context_and_message_origin_delegate_to_api(monkeypatch):
    _joined(monkeypatch)
    monkeypatch.setattr(server.api, "agent_context", lambda agent_id, api_key: {"agent_id": agent_id, "k": api_key})
    seen = []

    def fake_origin(agent_id, api_key, message_id):
        seen.append(message_id)
        if message_id == "bad":
            raise server.api.GatewayError("404")
        return {"message_id": message_id, "sender_kind": "operator"}

    monkeypatch.setattr(server.api, "message_origin", fake_origin)

    assert _call(server.agent_context) == {"agent_id": "agent-aaa111", "k": "k"}
    assert _call(server.agent_message_origin, "m1") == {"message_id": "m1", "sender_kind": "operator"}
    assert "error" in _call(server.agent_message_origin, "bad")
    assert seen == ["m1", "bad"]


def _doc(tool):
    return tool.__doc__ if callable(tool) else tool.fn.__doc__


def test_new_tool_docstrings_say_system_dashboard_is_the_human_operator():
    for tool in (server.agent_context, server.agent_message_origin):
        doc = _doc(tool)
        assert "system-dashboard" in doc and "HUMAN OPERATOR" in doc


def test_operator_status_ack_is_optional_and_forwarded(monkeypatch):
    _joined(monkeypatch)
    calls = []

    def fake_post(agent_id, api_key, kind, body, title=None, task_id=None, ack=None):
        calls.append((kind, body, ack))
        return {"ok": True}

    monkeypatch.setattr(server.api, "operator_post", fake_post)
    _call(server.operator_status, "plain")
    _call(server.operator_status, "got it", ack="b-1")
    assert calls == [("status", "plain", None), ("status", "got it", "b-1")]


def test_ams_onboarding_prompt_and_resource_registered():
    import asyncio

    prompts = asyncio.run(server.mcp.list_prompts())
    assert "ams-onboarding" in [p.name for p in prompts]
    resources = asyncio.run(server.mcp.list_resources())
    assert "ams-onboarding" in [r.name for r in resources]
    text = server.ams_onboarding_prompt()
    for needle in ("HUMAN OPERATOR", "operator_report", "operator_status", "operator_ask",
                   "in_reply_to", "agent_send_message", "agent_message_origin"):
        assert needle in text


def test_agent_join_sends_enrollment_code_from_env(monkeypatch, tmp_path):
    import responses

    monkeypatch.setenv("AGENT_MESH_HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_MESH_ENROLL_CODE", "enr_MCPCODE")
    monkeypatch.setattr(server, "_heartbeat", None)
    monkeypatch.setattr(
        server.identity_mod,
        "build_identity",
        lambda role=None, display_name="", domain="", project=None, cwd=None: {
            **IDENTITY, "role": "backend", "display_name": "", "domain": "", "project": "p",
        },
    )

    class QuietHeartbeat:
        def __init__(self, agent_id, api_key):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(server, "HeartbeatThread", QuietHeartbeat)
    monkeypatch.setattr(server.api, "whoami", lambda agent_id, api_key: {"agent_id": agent_id})

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            f"{server.config.gateway_url()}/agents/join",
            json={"agent_id": "agent-planned1", "api_key": "k1", "status": "ONLINE"},
            status=200,
        )
        result = _call(server.agent_join, role="backend")
        sent = rsps.calls[0].request.headers

    assert sent["X-Enrollment-Token"] == "enr_MCPCODE"
    assert result == {"agent_id": "agent-planned1"}
