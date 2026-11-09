"""G1 client side: opt-in ack mode. Default calls must keep the old wire behaviour."""
import json

import pytest
import requests
import responses

from agent_mesh_client import api, config


def url(path):
    return f"{config.gateway_url()}{path}"


MSG = {
    "message_id": "m1", "from_agent": "a", "to_agent": "b", "body": "hi",
    "created_at": "2026-11-08T00:00:00",
}


class Stop(BaseException):
    """Raised from the patched sleep to leave listen_inbox's endless reconnect loop."""


@pytest.fixture()
def stop_after_one_connection(monkeypatch):
    def _sleep(_):
        raise Stop()

    monkeypatch.setattr(api.time, "sleep", _sleep)


def sse(*events):
    return "".join(f"event: message\ndata: {json.dumps(e)}\n\n" for e in events)


@responses.activate
def test_inbox_default_sends_no_ack_param_old_wire_behaviour():
    responses.add(responses.GET, url("/messages/inbox"), json=[], status=200)
    assert api.inbox("a", "k") == []
    assert responses.calls[0].request.url == url("/messages/inbox")  # no query string at all


@responses.activate
def test_inbox_ack_true_sends_ack_param():
    responses.add(responses.GET, url("/messages/inbox"), json=[{**MSG, "status": "delivering"}], status=200)
    assert api.inbox("a", "k", ack=True)[0]["status"] == "delivering"
    assert responses.calls[0].request.url == url("/messages/inbox") + "?ack=1"


@responses.activate
def test_ack_posts_ids_and_batches_and_dedupes():
    responses.add(responses.POST, url("/messages/ack"), json={"ok": True, "count": 1}, status=200)
    assert api.ack("a", "k", ["m1", "m1", "m2"]) == {"ok": True, "count": 1}
    assert json.loads(responses.calls[0].request.body) == {"message_ids": ["m1", "m2"]}
    assert responses.calls[0].request.headers["Authorization"] == "Bearer k"
    responses.calls.reset()
    api.ack("a", "k", [f"id{i}" for i in range(1200)])
    assert [len(json.loads(c.request.body)["message_ids"]) for c in responses.calls] == [500, 500, 200]


@responses.activate
def test_ack_old_gateway_404_raises_http_error():
    responses.add(responses.POST, url("/messages/ack"), json={"detail": "Not Found"}, status=404)
    with pytest.raises(requests.HTTPError) as ei:
        api.ack("a", "k", ["m1"])
    assert ei.value.response.status_code == 404


@responses.activate
def test_listen_default_is_legacy_no_query_no_ack(stop_after_one_connection):
    responses.add(responses.GET, url("/messages/inbox/stream"), body=sse(MSG), status=200)
    got = []
    with pytest.raises(Stop):
        api.listen_inbox("a", "k", got.append)
    assert [m["message_id"] for m in got] == ["m1"]
    assert responses.calls[0].request.url == url("/messages/inbox/stream")
    assert len(responses.calls) == 1  # nothing was acked


@responses.activate
def test_listen_ack_mode_acks_after_callback_returns(stop_after_one_connection):
    order = []
    responses.add(responses.GET, url("/messages/inbox/stream"), body=sse({**MSG, "status": "delivering"}), status=200)
    responses.add(responses.POST, url("/messages/ack"), json={"ok": True, "count": 1}, status=200)

    def cb(m):
        order.append(("cb", len(responses.calls)))  # only the stream GET happened so far

    with pytest.raises(Stop):
        api.listen_inbox("a", "k", cb, ack=True)
    assert order == [("cb", 1)]
    assert responses.calls[0].request.url.endswith("/messages/inbox/stream?ack=1")
    assert json.loads(responses.calls[1].request.body) == {"message_ids": ["m1"]}


@responses.activate
def test_listen_ack_mode_callback_exception_means_no_ack_and_stream_continues(stop_after_one_connection):
    m1, m2 = {**MSG, "status": "delivering"}, {**MSG, "message_id": "m2", "status": "delivering"}
    responses.add(responses.GET, url("/messages/inbox/stream"), body=sse(m1, m2), status=200)
    responses.add(responses.POST, url("/messages/ack"), json={"ok": True, "count": 1}, status=200)
    errors = []

    def cb(m):
        if m["message_id"] == "m1":
            raise ValueError("could not persist")

    with pytest.raises(Stop):
        api.listen_inbox("a", "k", cb, ack=True, on_error=lambda e, m: errors.append((type(e).__name__, m["message_id"])))
    acks = [json.loads(c.request.body)["message_ids"] for c in responses.calls if c.request.method == "POST"]
    assert acks == [["m2"]]  # m1 not acked -> gateway redelivers it after the lease
    assert errors == [("ValueError", "m1")]


@responses.activate
def test_listen_ack_mode_message_without_delivering_status_is_not_acked(stop_after_one_connection):
    """Older gateway ignores ?ack=1 and pushes legacy events (no status): nothing to ack, no 404 noise."""
    responses.add(responses.GET, url("/messages/inbox/stream"), body=sse(MSG), status=200)
    got = []
    with pytest.raises(Stop):
        api.listen_inbox("a", "k", got.append, ack=True)
    assert len(got) == 1 and len(responses.calls) == 1


@responses.activate
def test_listen_ack_404_falls_back_to_legacy_on_reconnect(monkeypatch):
    sleeps = []

    def _sleep(_):
        sleeps.append(1)
        if len(sleeps) >= 2:
            raise Stop()

    monkeypatch.setattr(api.time, "sleep", _sleep)
    responses.add(responses.GET, url("/messages/inbox/stream"), body=sse({**MSG, "status": "delivering"}), status=200)
    responses.add(responses.POST, url("/messages/ack"), json={"detail": "Not Found"}, status=404)
    with pytest.raises(Stop):
        api.listen_inbox("a", "k", lambda m: None, ack=True)
    streams = [c.request.url for c in responses.calls if c.request.method == "GET"]
    assert streams[0].endswith("?ack=1") and streams[1] == url("/messages/inbox/stream")  # reconnect without ack


@responses.activate
def test_listen_ack_lost_ack_is_swallowed_and_stream_continues(stop_after_one_connection):
    m1, m2 = {**MSG, "status": "delivering"}, {**MSG, "message_id": "m2", "status": "delivering"}
    responses.add(responses.GET, url("/messages/inbox/stream"), body=sse(m1, m2), status=200)
    responses.add(responses.POST, url("/messages/ack"), body=requests.ConnectionError("cut"))
    got = []
    with pytest.raises(Stop):
        api.listen_inbox("a", "k", got.append, ack=True)
    assert [m["message_id"] for m in got] == ["m1", "m2"]
