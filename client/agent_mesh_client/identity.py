import getpass
import hashlib
import os
import socket
import subprocess

from . import config


def get_user_id() -> str:
    return getpass.getuser()


def get_machine_id() -> str:
    return socket.gethostname()


def detect_git_root(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except FileNotFoundError:
        return None
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def compute_agent_id(user_id: str, machine_id: str, workspace: str, role: str) -> str:
    raw = f"{user_id}:{machine_id}:{workspace}:{role}"
    digest = hashlib.sha1(raw.encode()).hexdigest()[:10]
    return f"agent-{digest}"


def build_identity(
    role: str | None = None,
    display_name: str = "",
    domain: str = "",
    project: str | None = None,
    cwd: str | None = None,
) -> dict:
    cwd = cwd or os.getcwd()
    user_id = get_user_id()
    machine_id = get_machine_id()
    workspace = detect_git_root(cwd) or os.path.abspath(cwd)

    if role is None:
        saved = config.get_role(workspace)
        if saved is None:
            raise ValueError(
                f"No role known for workspace {workspace!r}. Pass role explicitly "
                "the first time you join this workspace, e.g. "
                "`agentctl join --role backend` or MCP `agent_join(role=...)`."
            )
        role = saved["role"]
        display_name = display_name or saved.get("display_name", "")
        domain = domain or saved.get("domain", "")
        project = project or saved.get("project") or workspace
    else:
        config.save_role(workspace, role, display_name, domain, project)
        saved = config.get_role(workspace)
        display_name = saved.get("display_name", "")
        domain = saved.get("domain", "")
        project = saved.get("project") or workspace

    return {
        "user_id": user_id,
        "machine_id": machine_id,
        "workspace": workspace,
        "role": role,
        "display_name": display_name,
        "domain": domain,
        "project": project,
        "agent_id": compute_agent_id(user_id, machine_id, workspace, role),
    }
