import requests
from mcp.server.fastmcp import FastMCP

from agent_mesh_client import api, config
from agent_mesh_client import identity as identity_mod
from agent_mesh_client.heartbeat import HeartbeatThread

mcp = FastMCP("agent-mesh")

_heartbeat: HeartbeatThread | None = None


def _ensure_joined() -> tuple[str, str]:
    global _heartbeat
    ident = identity_mod.build_identity()
    api_key = config.get_api_key(ident["agent_id"])
    if not api_key:
        data = api.join(ident, capabilities=[])
        agent_id, api_key = data["agent_id"], data["api_key"]
    else:
        agent_id = ident["agent_id"]
    if _heartbeat is None:
        _heartbeat = HeartbeatThread(agent_id, api_key)
        _heartbeat.start()
    return agent_id, api_key


@mcp.tool()
def agent_join() -> dict:
    """Register this Claude Code session as an agent in the mesh."""
    global _heartbeat
    # Unlike the other tools, agent_join ALWAYS re-registers rather than
    # trusting a cached local key. join is idempotent server-side, and this is
    # what lets a session self-heal after the Gateway's database is reset --
    # otherwise a stale local key would 401 every call with no way to recover.
    ident = identity_mod.build_identity()
    data = api.join(ident, capabilities=[])
    agent_id, api_key = data["agent_id"], data["api_key"]
    # Restart the heartbeat on the freshly issued key. A thread started earlier
    # in this process holds the OLD key, which after a Gateway reset would 401
    # forever and leave the agent stuck OFFLINE even though re-registration
    # succeeded.
    if _heartbeat is not None:
        _heartbeat.stop()
    _heartbeat = HeartbeatThread(agent_id, api_key)
    _heartbeat.start()
    return api.whoami(agent_id, api_key)


@mcp.tool()
def agent_whoami() -> dict:
    """Return this agent's identity and current status."""
    agent_id, api_key = _ensure_joined()
    return api.whoami(agent_id, api_key)


@mcp.tool()
def agent_list() -> list:
    """List all known agents and whether they are ONLINE or OFFLINE."""
    agent_id, api_key = _ensure_joined()
    return api.list_agents(agent_id, api_key)


@mcp.tool()
def agent_get(agent_id: str) -> dict:
    """Get details for a single agent by its agent_id."""
    _my_id, api_key = _ensure_joined()
    try:
        return api.get_agent(agent_id, api_key)
    except requests.HTTPError:
        return {"error": f"agent {agent_id} not found"}


@mcp.tool()
def agent_send_message(to: str, body: str) -> dict:
    """Send a message to another agent, identified by its agent_id."""
    agent_id, api_key = _ensure_joined()
    return api.send_message(agent_id, api_key, to, body)


@mcp.tool()
def agent_inbox() -> list:
    """Fetch and mark-delivered all pending messages addressed to this agent."""
    agent_id, api_key = _ensure_joined()
    return api.inbox(agent_id, api_key)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
