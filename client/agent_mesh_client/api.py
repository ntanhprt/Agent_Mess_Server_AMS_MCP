import os
import socket
import uuid

import requests

from . import config


class GatewayError(Exception):
    pass


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def join(identity: dict, capabilities: list[str]) -> dict:
    api_key = config.get_api_key(identity["agent_id"])
    payload = {
        **identity,
        "capabilities": capabilities,
        "api_key": api_key,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "session_id": str(uuid.uuid4()),
    }
    resp = requests.post(
        f"{config.gateway_url()}/agents/join",
        json=payload,
        headers={"X-Join-Token": config.join_token()},
        timeout=5,
    )
    if resp.status_code != 200:
        raise GatewayError(resp.text)
    data = resp.json()
    config.save_credential(data["agent_id"], data["api_key"])
    return data


def heartbeat(agent_id: str, api_key: str) -> None:
    resp = requests.post(
        f"{config.gateway_url()}/agents/heartbeat", headers=_headers(api_key), timeout=5
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


def inbox(agent_id: str, api_key: str) -> list[dict]:
    resp = requests.get(
        f"{config.gateway_url()}/messages/inbox", headers=_headers(api_key), timeout=5
    )
    resp.raise_for_status()
    return resp.json()


def create_task(
    agent_id: str,
    api_key: str,
    title: str,
    description: str | None = None,
    project: str | None = None,
    required_role: str | None = None,
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
