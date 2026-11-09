"""Inbox poller: AMS cannot push into an agent session when the host is not reachable from
the gateway, so an agent must PULL. This module pulls the inbox on an interval, appends new
messages (deduplicated by message_id) to ~/.agent-mesh/inbox/<agent_id>.jsonl, acks them,
flushes the outbox of queued reports, and survives gateway outages (exponential backoff)
and a lost session (re-join with the saved identity)."""
import json
import logging
import os
import threading

import requests

from . import api, state

logger = logging.getLogger(__name__)
MAX_BACKOFF = 60.0


def _seen_ids(path) -> set[str]:
    seen: set[str] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    mid = json.loads(line).get("message_id")
                except ValueError:
                    continue
                if mid:
                    seen.add(mid)
    except OSError:
        pass
    return seen


def _append_lines(path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("".join(line + "\n" for line in lines))
        fh.flush()
        os.fsync(fh.fileno())


def flush_outbox(agent_id: str, api_key: str) -> int:
    """Send queued reports/status oldest first; stop at the first network failure."""
    items = state.outbox_list(agent_id)
    sent = 0
    while items:
        it = items[0]
        try:
            api.operator_post(
                agent_id, api_key, it["kind"], it["body"], title=it.get("title"), task_id=it.get("task_id")
            )
        except (requests.ConnectionError, requests.Timeout):
            break
        except (api.GatewayError, requests.RequestException, KeyError) as exc:
            logger.warning("dropping undeliverable outbox item: %s", exc)
        items.pop(0)
        sent += 1
    if sent:
        state.outbox_replace(agent_id, items)
    return sent


def poll_once(agent_id: str, api_key: str) -> list[dict]:
    """Fetch the inbox, persist NEW messages (oldest first), then ack. Returns the new ones."""
    msgs = api.inbox(agent_id, api_key, ack=True)
    path = state.inbox_log_file(agent_id)
    seen = _seen_ids(path)
    new = [m for m in msgs if m.get("message_id") not in seen]
    new.sort(key=lambda m: m.get("created_at") or "")
    if new:
        _append_lines(path, [json.dumps(m, ensure_ascii=False) for m in new])
    ids = [m["message_id"] for m in msgs if m.get("message_id")]
    if ids:
        try:
            api.ack(agent_id, api_key, ids)
        except requests.HTTPError:
            pass  # older gateway without ack: messages were delivered at read time
    return new


def run(agent_id: str, api_key: str, interval: float, on_new, rejoin=None, stop: threading.Event | None = None):
    """Loop until `stop` is set. rejoin() -> (agent_id, api_key) is called on HTTP 401."""
    stop = stop or threading.Event()
    delay = interval
    while not stop.is_set():
        try:
            flush_outbox(agent_id, api_key)
            new = poll_once(agent_id, api_key)
            if new:
                on_new(new)
            delay = interval
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401 and rejoin:
                try:
                    agent_id, api_key = rejoin()
                    delay = interval
                    continue
                except (api.GatewayError, requests.RequestException) as exc2:
                    logger.warning("rejoin failed: %s", exc2)
            delay = min(max(delay, 1.0) * 2, MAX_BACKOFF)
        except requests.RequestException as exc:
            logger.warning("gateway unreachable: %s", exc)
            delay = min(max(delay, 1.0) * 2, MAX_BACKOFF)
        stop.wait(delay)
