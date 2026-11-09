import json
import os
import socket
import time
import uuid
from typing import Callable

import requests

from . import config, state
from .identity import get_lan_ip


class GatewayError(Exception):
    pass


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def join(identity: dict, capabilities: list[str], enroll_code: str | None = None) -> dict:
    derived_id = identity["agent_id"]
    identity = {**identity, "agent_id": config.resolve_agent_id(derived_id)}
    api_key = config.get_api_key(identity["agent_id"])
    # An enrollment code is single use: send it only while this agent has no saved
    # credential, so a leftover AGENT_MESH_ENROLL_CODE never breaks a later re-join.
    code = None if api_key else (enroll_code or config.enroll_code())
    payload = {
        **identity,
        "capabilities": capabilities,
        "api_key": api_key,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "session_id": str(uuid.uuid4()),
        "lan_ip": get_lan_ip(),
    }
    headers = {"X-Join-Token": config.join_token()}
    if code:
        headers["X-Enrollment-Token"] = code
    resp = requests.post(
        f"{config.gateway_url()}/agents/join",
        json=payload,
        headers=headers,
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    data = resp.json()
    config.save_credential(data["agent_id"], data["api_key"])
    if data["agent_id"] != derived_id:  # enrollment issued the planned id
        config.save_alias(derived_id, data["agent_id"])
    # Remember how to fast-rejoin after a restart/power loss. Never fatal.
    try:
        state.record_join(identity, data["agent_id"], config.gateway_url())
    except OSError:
        pass
    return data


def heartbeat(agent_id: str, api_key: str) -> None:
    resp = requests.post(
        f"{config.gateway_url()}/agents/heartbeat",
        headers=_headers(api_key),
        json={"lan_ip": get_lan_ip()},
        timeout=5,
    )
    resp.raise_for_status()


def whoami(agent_id: str, api_key: str) -> dict:
    resp = requests.get(f"{config.gateway_url()}/agents/me", headers=_headers(api_key), timeout=5)
    resp.raise_for_status()
    return resp.json()


def list_agents(agent_id: str, api_key: str) -> list[dict]:
    resp = requests.get(f"{config.gateway_url()}/agents", headers=_headers(api_key), timeout=5)
    resp.raise_for_status()
    return resp.json()


def get_agent(agent_id: str, api_key: str) -> dict:
    resp = requests.get(
        f"{config.gateway_url()}/agents/{agent_id}", headers=_headers(api_key), timeout=5
    )
    resp.raise_for_status()
    return resp.json()


def send_message(agent_id: str, api_key: str, to: str, body: str) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/messages",
        headers=_headers(api_key),
        json={"to": to, "body": body},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def inbox(agent_id: str, api_key: str, ack: bool = False) -> list[dict]:
    """Read the inbox. Default (ack=False) is the legacy behaviour: the gateway
    marks every returned message delivered at read time (at-most-once: a lost
    response loses them). With ack=True (needs a gateway that supports it; an older
    gateway silently ignores the flag and behaves as legacy) the messages come back
    with status "delivering" + lease_until and are NOT delivered until you call
    ack() with their ids after you have durably handled them; un-acked messages
    are returned again after the gateway's visibility timeout. Handle by message_id
    idempotently, redelivery is expected."""
    resp = requests.get(
        f"{config.gateway_url()}/messages/inbox",
        headers=_headers(api_key),
        params={"ack": "1"} if ack else None,
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


_ACK_BATCH = 500


def _post_ack(api_key: str, ids: list[str]) -> dict:
    ids = list(dict.fromkeys(ids))
    result: dict = {"ok": True, "count": 0}
    for i in range(0, len(ids), _ACK_BATCH):
        resp = requests.post(
            f"{config.gateway_url()}/messages/ack",
            headers=_headers(api_key),
            json={"message_ids": ids[i : i + _ACK_BATCH]},
            timeout=5,
        )
        resp.raise_for_status()
        result = resp.json()
    return result


def ack(agent_id: str, api_key: str, ids: list[str]) -> dict:
    """Confirm messages received via inbox(ack=True) / listen_inbox(ack=True).
    Idempotent; unknown or foreign ids are ignored by the gateway. Raises
    requests.HTTPError (404/405 on a gateway that predates ack support)."""
    return _post_ack(api_key, ids)


def listen_inbox(
    agent_id: str,
    api_key: str,
    on_message: Callable[[dict], None],
    ack: bool = False,
    on_error: Callable[[BaseException, dict], None] | None = None,
) -> None:
    """Giữ 1 kết nối SSE mở tới AMS và gọi on_message() ngay khi có tin mới --
    đây là kênh AMS chủ động đẩy tin, thay cho việc gọi inbox() lặp lại theo
    timer. Chặn (blocking) cho tới khi kết nối bị ngắt hoặc lỗi; gọi trong 1
    thread/process riêng nếu cần chạy nền. Tự động thử lại khi mất kết nối.

    ack=False (default): legacy -- the gateway marks each pushed message delivered.
    ack=True: the gateway only LEASES each message. on_message() must durably
    handle it; if it returns normally the message is acked (POST /messages/ack),
    if it raises (on_error(exc, msg) is called, the stream keeps running) nothing
    is acked and the gateway pushes the message again after its visibility
    timeout. Delivery is therefore at-least-once: make on_message idempotent by
    message_id. If the gateway has no ack endpoint (404/405) the listener drops
    back to legacy mode on its next reconnect."""
    ack_enabled = ack
    while True:
        try:
            with requests.get(
                f"{config.gateway_url()}/messages/inbox/stream",
                headers=_headers(api_key),
                params={"ack": "1"} if ack_enabled else None,
                stream=True,
                timeout=None,
            ) as resp:
                resp.raise_for_status()
                event_lines: list[str] = []
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if raw_line is None:
                        continue
                    if raw_line == "":
                        data_line = next(
                            (l[5:].strip() for l in event_lines if l.startswith("data:")), None
                        )
                        event_lines = []
                        if data_line:
                            msg = json.loads(data_line)
                            if not ack_enabled:
                                on_message(msg)
                                continue
                            try:
                                on_message(msg)
                            except Exception as exc:
                                if on_error is not None:
                                    on_error(exc, msg)
                                continue  # not acked -> redelivered after the lease
                            if msg.get("status") == "delivering" and msg.get("message_id"):
                                try:
                                    _post_ack(api_key, [msg["message_id"]])
                                except requests.HTTPError as exc:
                                    if getattr(exc.response, "status_code", None) in (404, 405):
                                        ack_enabled = False
                                except requests.RequestException:
                                    pass  # ack lost -> redelivered, caller dedupes
                        continue
                    event_lines.append(raw_line)
        except requests.RequestException:
            pass  # gateway tạm thời không tới được -- thử reconnect sau khi chờ 1 nhịp
        time.sleep(3)


def create_task(
    agent_id: str,
    api_key: str,
    title: str,
    description: str | None = None,
    project: str | None = None,
    required_role: str | None = None,
    required_capabilities: list[str] | None = None,
    input_ref: str | None = None,
    priority: str = "normal",
    depends_on: list[str] | None = None,
) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/tasks",
        headers=_headers(api_key),
        json={
            "title": title,
            "description": description,
            "project": project,
            "required_role": required_role,
            "required_capabilities": required_capabilities or [],
            "input_ref": input_ref,
            "priority": priority,
            "depends_on": depends_on or [],
        },
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def list_tasks(
    agent_id: str,
    api_key: str,
    status: str | None = None,
    required_role: str | None = None,
    project: str | None = None,
) -> list[dict]:
    params = {}
    if status:
        params["status"] = status
    if required_role:
        params["required_role"] = required_role
    if project:
        params["project"] = project
    resp = requests.get(
        f"{config.gateway_url()}/tasks", headers=_headers(api_key), params=params, timeout=5
    )
    resp.raise_for_status()
    return resp.json()


def get_task(agent_id: str, api_key: str, task_id: str) -> dict:
    resp = requests.get(
        f"{config.gateway_url()}/tasks/{task_id}", headers=_headers(api_key), timeout=5
    )
    resp.raise_for_status()
    return resp.json()


def claim_task(agent_id: str, api_key: str, task_id: str) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/tasks/{task_id}/claim", headers=_headers(api_key), timeout=5
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def update_task_status(agent_id: str, api_key: str, task_id: str, status: str, note: str | None = None) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/tasks/{task_id}/status",
        headers=_headers(api_key),
        json={"status": status, "note": note},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def log_work(agent_id: str, api_key: str, title: str, detail: str | None = None, date: str | None = None) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/worklog",
        headers=_headers(api_key),
        json={"title": title, "detail": detail, "date": date},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def set_openproject_scope(agent_id: str, api_key: str, project_ids: list[str]) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/agents/me/openproject-scope",
        headers=_headers(api_key),
        json={"project_ids": project_ids},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def complete_task(
    agent_id: str, api_key: str, task_id: str, summary: str, artifact_ref: str | None = None
) -> dict:
    resp = requests.post(
        f"{config.gateway_url()}/tasks/{task_id}/complete",
        headers=_headers(api_key),
        json={"summary": summary, "artifact_ref": artifact_ref},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def operator_post(
    agent_id: str,
    api_key: str,
    kind: str,
    body: str,
    title: str | None = None,
    task_id: str | None = None,
    ack: str | None = None,
) -> dict:
    """Push a report / status / question to the web dashboard (operator channel)."""
    payload = {"kind": kind, "body": body, "title": title, "task_id": task_id}
    if ack is not None:  # acknowledges a broadcast (kind="status" only)
        payload["ack"] = ack
    resp = requests.post(
        f"{config.gateway_url()}/operator/events",
        headers=_headers(api_key),
        json=payload,
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def operator_get(agent_id: str, api_key: str, event_id: str) -> dict:
    resp = requests.get(
        f"{config.gateway_url()}/operator/events/{event_id}",
        headers=_headers(api_key),
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def operator_resolve(agent_id: str, api_key: str, event_id: str, answer: str) -> dict:
    """Mark an open question as answered via the CLI (the human answered locally)."""
    resp = requests.post(
        f"{config.gateway_url()}/operator/events/{event_id}/resolve",
        headers=_headers(api_key),
        json={"answer": answer},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def agent_context(agent_id: str, api_key: str) -> dict:
    """Everything the gateway knows about THIS agent (GET /agents/me/context)."""
    resp = requests.get(f"{config.gateway_url()}/agents/me/context", headers=_headers(api_key), timeout=5)
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()


def message_origin(agent_id: str, api_key: str, message_id: str) -> dict:
    """The original message + sender_kind (GET /agents/me/messages/{id}); 404 -> GatewayError."""
    resp = requests.get(
        f"{config.gateway_url()}/agents/me/messages/{message_id}",
        headers=_headers(api_key),
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    return resp.json()
