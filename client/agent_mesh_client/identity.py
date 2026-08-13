import getpass
import hashlib
import os
import socket
import subprocess


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


def compute_agent_id(user_id: str, machine_id: str, workspace: str) -> str:
    raw = f"{user_id}:{machine_id}:{workspace}"
    digest = hashlib.sha1(raw.encode()).hexdigest()[:10]
    return f"agent-{digest}"


def build_identity(cwd: str | None = None) -> dict:
    cwd = cwd or os.getcwd()
    user_id = get_user_id()
    machine_id = get_machine_id()
    workspace = detect_git_root(cwd) or os.path.abspath(cwd)
    return {
        "user_id": user_id,
        "machine_id": machine_id,
        "workspace": workspace,
        "agent_id": compute_agent_id(user_id, machine_id, workspace),
    }
