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
