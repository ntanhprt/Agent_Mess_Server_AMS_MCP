import time

from agent_mesh_client.heartbeat import HeartbeatThread


def test_heartbeat_thread_calls_api_repeatedly_until_stopped(monkeypatch):
    calls = []

    def fake_heartbeat(agent_id, api_key):
        calls.append((agent_id, api_key))

    monkeypatch.setattr("agent_mesh_client.api.heartbeat", fake_heartbeat)

    hb = HeartbeatThread("agent-aaa111", "key-a", interval=0.05)
    hb.start()
    time.sleep(0.2)
    hb.stop()

    count_after_stop = len(calls)
    time.sleep(0.2)

    assert count_after_stop >= 2
    assert len(calls) == count_after_stop
    assert all(c == ("agent-aaa111", "key-a") for c in calls)


def test_heartbeat_thread_survives_failing_calls(monkeypatch, caplog):
    calls = []

    def failing_heartbeat(agent_id, api_key):
        calls.append((agent_id, api_key))
        raise ConnectionError("gateway unreachable")

    monkeypatch.setattr("agent_mesh_client.api.heartbeat", failing_heartbeat)

    with caplog.at_level("WARNING", logger="agent_mesh_client.heartbeat"):
        hb = HeartbeatThread("agent-aaa111", "key-a", interval=0.05)
        hb.start()
        time.sleep(0.2)
        hb.stop()

    # The loop keeps retrying past the first failure instead of dying.
    assert len(calls) >= 2
    # And the failure is visible rather than silently swallowed.
    assert any("heartbeat failed" in r.message for r in caplog.records)
