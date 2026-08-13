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
