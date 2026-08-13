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
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))

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

    result = _call(server.agent_join)

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
    monkeypatch.setattr(server.identity_mod, "build_identity", lambda: dict(IDENTITY))
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

    _call(server.agent_join)

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
