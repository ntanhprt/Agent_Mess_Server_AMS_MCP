import requests
from mcp.server.fastmcp import FastMCP

from agent_mesh_client import api, config, artifacts
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
def agent_join(role: str, display_name: str = "", domain: str = "", project: str | None = None) -> dict:
    """Register this Claude Code session as an agent in the mesh with the given role.

    role is required on every call to this tool (it has no default). project
    is optional -- omit it to default to this workspace's path, or pass an
    explicit project name/id to join a specific EXISTING project (ask
    whoever created that project for its exact name/id).
    You typically only need to call agent_join once per workspace, though --
    once registered, the other tools automatically resolve the already-
    established role/project for this workspace on their own and don't
    require agent_join to be called again. Calling agent_join again with a
    DIFFERENT role registers a different agent, since role is part of this
    agent's identity (project is not, and can be changed on a later
    agent_join call).
    """
    global _heartbeat
    # Unlike the other tools, agent_join ALWAYS re-registers rather than
    # trusting a cached local key. join is idempotent server-side, and this is
    # what lets a session self-heal after the Gateway's database is reset --
    # otherwise a stale local key would 401 every call with no way to recover.
    try:
        ident = identity_mod.build_identity(role=role, display_name=display_name, domain=domain, project=project)
    except ValueError as exc:
        return {"error": str(exc)}
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


@mcp.tool()
def task_create(
    title: str,
    description: str | None = None,
    project: str | None = None,
    required_role: str | None = None,
    input_ref: str | None = None,
    priority: str = "normal",
    depends_on: list[str] | None = None,
) -> dict:
    """Create a task. Leave required_role unset for anyone to claim it.
    Leave project unset to create it in your own declared project."""
    agent_id, api_key = _ensure_joined()
    return api.create_task(
        agent_id,
        api_key,
        title,
        description=description,
        project=project,
        required_role=required_role,
        input_ref=input_ref,
        priority=priority,
        depends_on=depends_on,
    )


@mcp.tool()
def task_list(status: str = "READY", required_role: str | None = None, project: str | None = None) -> list:
    """List tasks. With no arguments, shows READY tasks in your own project
    claimable by this agent (matching its own role, or with no required_role
    at all). Pass project to look at a different project's queue."""
    agent_id, api_key = _ensure_joined()
    if required_role is not None:
        return api.list_tasks(agent_id, api_key, status=status, required_role=required_role, project=project)
    my_role = identity_mod.build_identity().get("role")
    tasks = api.list_tasks(agent_id, api_key, status=status, project=project)
    return [t for t in tasks if t["required_role"] in (None, my_role)]


@mcp.tool()
def task_get(task_id: str) -> dict:
    """Get details for one task."""
    agent_id, api_key = _ensure_joined()
    return api.get_task(agent_id, api_key, task_id)


@mcp.tool()
def task_claim(task_id: str) -> dict:
    """Atomically claim a READY task matching this agent's role."""
    agent_id, api_key = _ensure_joined()
    return api.claim_task(agent_id, api_key, task_id)


@mcp.tool()
def task_update_status(task_id: str, status: str, note: str | None = None) -> dict:
    """Move a claimed task to IN_PROGRESS/REVIEW, or FAILED (which requeues it)."""
    agent_id, api_key = _ensure_joined()
    return api.update_task_status(agent_id, api_key, task_id, status, note=note)


@mcp.tool()
def task_complete(task_id: str, summary: str, artifact_ref: str | None = None) -> dict:
    """Mark a task DONE, optionally attaching an artifact_ref (e.g. a MinIO object key)."""
    agent_id, api_key = _ensure_joined()
    return api.complete_task(agent_id, api_key, task_id, summary, artifact_ref=artifact_ref)


@mcp.tool()
def task_upload_artifact(path: str, task_id: str) -> str:
    """Upload a local file to MinIO for a task, returning the object key to
    pass as artifact_ref to task_complete (or input_ref/a message to another agent)."""
    return artifacts.upload_artifact(path, task_id)


@mcp.tool()
def task_download_artifact(object_key: str, dest_path: str) -> None:
    """Download a MinIO object (an artifact_ref from a task) to a local path."""
    artifacts.download_artifact(object_key, dest_path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
