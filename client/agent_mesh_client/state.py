"""Local, crash-safe join state + per-agent work checkpoints.

Layout under the AMS home dir (AGENT_MESH_HOME, default ~/.agent-mesh):
  join_state.json            {workspace: {agent_id, role, display_name, domain, project,
                              gateway_url, joined_at}}   -- how to fast-rejoin after a restart
  checkpoints/<agent_id>.json {agent_id, task_id, note, docs[], extra, updated_at}
                              -- the unfinished work context to resume

Never stores the join token or the api key (those live only in credentials.json).
Every write is atomic (temp file in the same dir + fsync + os.replace), so a power loss
leaves either the old or the new file, never a truncated one. A corrupt/unreadable file
is treated as empty rather than crashing a join.
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path

from . import config

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")
MAX_DOCS = 50


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _state_file() -> Path:
    return config._cred_dir() / "join_state.json"


def _checkpoint_file(agent_id: str) -> Path:
    return config._cred_dir() / "checkpoints" / (_SAFE_ID.sub("_", agent_id) + ".json")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---- join state ----
def record_join(identity: dict, agent_id: str, gateway_url: str) -> None:
    states = _read_json(_state_file())
    states[identity["workspace"]] = {
        "agent_id": agent_id,
        "role": identity.get("role"),
        "display_name": identity.get("display_name", ""),
        "domain": identity.get("domain", ""),
        "project": identity.get("project"),
        "gateway_url": gateway_url,
        "joined_at": _now(),
    }
    atomic_write_text(_state_file(), json.dumps(states, indent=2))


def get_join_state(workspace: str) -> dict | None:
    st = _read_json(_state_file()).get(workspace)
    return st if isinstance(st, dict) else None


# ---- work checkpoints ----
def load_checkpoint(agent_id: str) -> dict | None:
    cp = _read_json(_checkpoint_file(agent_id))
    return cp or None


def save_checkpoint(
    agent_id: str,
    task_id: str | None = None,
    note: str | None = None,
    docs: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    """Merge into the agent's checkpoint: given fields replace, omitted ones are kept.
    docs are appended (deduplicated, capped) -- references/paths of drafts, not contents."""
    cp = load_checkpoint(agent_id) or {"agent_id": agent_id, "docs": []}
    if task_id is not None:
        cp["task_id"] = task_id
    if note is not None:
        cp["note"] = note
    if docs:
        merged = list(cp.get("docs") or [])
        for d in docs:
            if d not in merged:
                merged.append(d)
        cp["docs"] = merged[-MAX_DOCS:]
    if extra:
        cp["extra"] = {**(cp.get("extra") or {}), **extra}
    cp["updated_at"] = _now()
    atomic_write_text(_checkpoint_file(agent_id), json.dumps(cp, indent=2))
    return cp


def clear_checkpoint(agent_id: str) -> bool:
    try:
        _checkpoint_file(agent_id).unlink()
        return True
    except OSError:
        return False


# ---- outbox: reports/status that could not be delivered (gateway unreachable) ----
def _outbox_file(agent_id: str) -> Path:
    return config._cred_dir() / "outbox" / (_SAFE_ID.sub("_", agent_id) + ".json")


def outbox_list(agent_id: str) -> list[dict]:
    try:
        data = json.loads(_outbox_file(agent_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _outbox_write(agent_id: str, items: list[dict]) -> None:
    if items:
        atomic_write_text(_outbox_file(agent_id), json.dumps(items, indent=2))
    else:
        try:
            _outbox_file(agent_id).unlink()
        except OSError:
            pass


def outbox_add(agent_id: str, kind: str, body: str, title: str | None, task_id: str | None) -> int:
    items = outbox_list(agent_id)
    items.append({"kind": kind, "body": body, "title": title, "task_id": task_id, "queued_at": _now()})
    items = items[-500:]
    _outbox_write(agent_id, items)
    return len(items)


def outbox_replace(agent_id: str, items: list[dict]) -> None:
    _outbox_write(agent_id, items)


def inbox_log_file(agent_id: str) -> Path:
    """Append-only JSONL of every inbox message the poller has received (one per line)."""
    return config._cred_dir() / "inbox" / (_SAFE_ID.sub("_", agent_id) + ".jsonl")
