import json
import os
from pathlib import Path

DEFAULT_GATEWAY_URL = "http://localhost:8420"
DEFAULT_JOIN_TOKEN = "dev-join-token-change-me"


def gateway_url() -> str:
    return os.environ.get("AGENT_GATEWAY_URL", DEFAULT_GATEWAY_URL)


def join_token() -> str:
    """Shared secret sent on /agents/join. Must match the Gateway's MESH_JOIN_TOKEN."""
    return os.environ.get("AGENT_MESH_JOIN_TOKEN", DEFAULT_JOIN_TOKEN)


def _cred_dir() -> Path:
    return Path(os.environ.get("AGENT_MESH_HOME", str(Path.home() / ".agent-mesh")))


def _cred_file() -> Path:
    return _cred_dir() / "credentials.json"


def load_credentials() -> dict:
    cred_file = _cred_file()
    if cred_file.exists():
        return json.loads(cred_file.read_text())
    return {}


def save_credential(agent_id: str, api_key: str) -> None:
    cred_dir = _cred_dir()
    # API keys are secrets: keep the store private to the owning user, which
    # matters on shared/multi-user hosts.
    cred_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    creds = load_credentials()
    creds[agent_id] = api_key
    cred_file = _cred_file()
    cred_file.write_text(json.dumps(creds))
    os.chmod(cred_file, 0o600)


def get_api_key(agent_id: str) -> str | None:
    return load_credentials().get(agent_id)


def _role_file() -> Path:
    return _cred_dir() / "roles.json"


def load_roles() -> dict:
    role_file = _role_file()
    if role_file.exists():
        return json.loads(role_file.read_text())
    return {}


def save_role(
    workspace: str,
    role: str,
    display_name: str = "",
    domain: str = "",
    project: str | None = None,
) -> None:
    cred_dir = _cred_dir()
    cred_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    roles = load_roles()
    existing = roles.get(workspace, {})
    roles[workspace] = {
        "role": role,
        "display_name": display_name or existing.get("display_name", ""),
        "domain": domain or existing.get("domain", ""),
        "project": project or existing.get("project"),
    }
    role_file = _role_file()
    role_file.write_text(json.dumps(roles))
    os.chmod(role_file, 0o600)


def get_role(workspace: str) -> dict | None:
    return load_roles().get(workspace)


DEFAULT_MINIO_ENDPOINT = "http://localhost:8421"
DEFAULT_MINIO_ACCESS_KEY = "agentmesh"
DEFAULT_MINIO_SECRET_KEY = "dev-minio-secret-change-me"


def minio_endpoint() -> str:
    return os.environ.get("AGENT_MESH_MINIO_ENDPOINT", DEFAULT_MINIO_ENDPOINT)


def minio_access_key() -> str:
    return os.environ.get("AGENT_MESH_MINIO_ACCESS_KEY", DEFAULT_MINIO_ACCESS_KEY)


def minio_secret_key() -> str:
    return os.environ.get("AGENT_MESH_MINIO_SECRET_KEY", DEFAULT_MINIO_SECRET_KEY)
