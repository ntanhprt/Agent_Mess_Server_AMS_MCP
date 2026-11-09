import requests
from mcp.server.fastmcp import FastMCP

from agent_mesh_client import api, config, artifacts, state
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
    me = api.whoami(agent_id, api_key)
    # Unfinished work saved before a crash/restart (see agent_checkpoint_save).
    cp = state.load_checkpoint(agent_id)
    if cp:
        me = {**me, "resume_checkpoint": cp}
    return me


@mcp.tool()
def agent_checkpoint_save(
    task_id: str | None = None, note: str | None = None, docs: list[str] | None = None
) -> dict:
    """Persist your in-progress work context locally (atomic, survives power loss/restart):
    the task_id, a short note on where you are, and paths/refs of drafts or documents.
    Call it at every milestone. On the next agent_join the checkpoint comes back as
    `resume_checkpoint`. Never store secrets here."""
    agent_id, _ = _ensure_joined()
    return state.save_checkpoint(agent_id, task_id=task_id, note=note, docs=docs)


@mcp.tool()
def agent_checkpoint_get() -> dict:
    """Return the saved in-progress checkpoint for this agent (empty dict if none)."""
    agent_id, _ = _ensure_joined()
    return state.load_checkpoint(agent_id) or {}


@mcp.tool()
def agent_checkpoint_clear() -> dict:
    """Clear the checkpoint once the work is finished."""
    agent_id, _ = _ensure_joined()
    return {"cleared": state.clear_checkpoint(agent_id)}


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
def log_work(title: str, detail: str | None = None, date: str | None = None) -> dict:
    """Ghi nhận 1 đầu việc VỪA hoàn thành vào Lịch làm việc (worklog) của AMS.

    Gọi tool này mỗi khi xong 1 việc đáng kể (fix bug, ship feature, hoàn
    thành 1 yêu cầu...) -- khác với task_complete (chỉ áp dụng cho Task đã tạo
    trong hàng đợi task của AMS), log_work dùng được cho MỌI việc, không cần
    có Task tương ứng. Xuất hiện trên trang Lịch làm việc (/admin/calendar) và
    được gom vào bản tổng kết cuối ngày.

    date (tuỳ chọn, "YYYY-MM-DD"): dùng khi QUÊN log và cần ghi bổ sung cho 1
    ngày đã qua -- entry sẽ được tính vào đúng ngày đó (file .md + tổng kết
    ngày hôm đó), dù gọi tool này muộn hơn. Không được là ngày tương lai. Bỏ
    trống = hôm nay, như trước giờ. Thời điểm gọi tool thật (audit trail) vẫn
    luôn được lưu riêng, không bị mất."""
    agent_id, api_key = _ensure_joined()
    return api.log_work(agent_id, api_key, title, detail=detail, date=date)


@mcp.tool()
def set_openproject_scope(project_ids: list[str]) -> dict:
    """Khai báo (các) project OpenProject (trên project.protontech.vn, KHÔNG
    phải project/workspace của AMS) mà agent này muốn bản tổng kết cuối ngày
    tự tra để liệt kê việc cần làm hôm sau -- CHỈ việc đang mở và gán cho chủ
    sở hữu OPENPROJECT_PAT, không phải toàn bộ việc mở của project.

    Không có mặc định -- mỗi agent tự khai báo project của riêng mình (vd
    project id "26" cho Javis AI, hoặc project id/slug khác cho các project cá
    nhân). NẾU vai trò (role) của agent này không rõ tương ứng project
    OpenProject nào, PHẢI hỏi thẳng người dùng trong chat lúc join mesh --
    KHÔNG được tự đoán project_ids. Gọi lại tool này để ghi đè toàn bộ danh
    sách cũ."""
    agent_id, api_key = _ensure_joined()
    return api.set_openproject_scope(agent_id, api_key, project_ids)


@mcp.tool()
def task_create(
    title: str,
    description: str | None = None,
    project: str | None = None,
    required_role: str | None = None,
    required_capabilities: list[str] | None = None,
    input_ref: str | None = None,
    priority: str = "normal",
    depends_on: list[str] | None = None,
) -> dict:
    """Create a task. Leave required_role unset for anyone to claim it.
    Leave project unset to create it in your own declared project.

    required_capabilities only actually gates claiming for agents that have
    "enforce_capabilities" turned on for themselves (set from the AMS
    dashboard, per-agent) -- a "general-purpose" agent (the default) can
    still claim it regardless of required_capabilities, as long as its role
    matches required_role."""
    agent_id, api_key = _ensure_joined()
    return api.create_task(
        agent_id,
        api_key,
        title,
        description=description,
        project=project,
        required_role=required_role,
        required_capabilities=required_capabilities,
        input_ref=input_ref,
        priority=priority,
        depends_on=depends_on,
    )


@mcp.tool()
def task_list(status: str = "READY", required_role: str | None = None, project: str | None = None) -> list:
    """List tasks. With no arguments, shows READY tasks in your own project
    that are actually claimable by THIS agent right now: role must match (or
    task has no required_role), and if you have enforce_capabilities turned
    on for yourself, required_capabilities must be a subset of your own
    capabilities too. Pass project to look at a different project's queue."""
    agent_id, api_key = _ensure_joined()
    if required_role is not None:
        return api.list_tasks(agent_id, api_key, status=status, required_role=required_role, project=project)
    me = api.whoami(agent_id, api_key)
    my_role = me.get("role")
    my_capabilities = set(me.get("capabilities") or [])
    enforce = bool(me.get("enforce_capabilities"))
    tasks = api.list_tasks(agent_id, api_key, status=status, project=project)

    def claimable(t: dict) -> bool:
        if t["required_role"] not in (None, my_role):
            return False
        if enforce and t.get("required_capabilities"):
            if not set(t["required_capabilities"]).issubset(my_capabilities):
                return False
        return True

    return [t for t in tasks if claimable(t)]


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


@mcp.tool()
def operator_report(body: str, title: str | None = None, task_id: str | None = None) -> dict:
    """Push a RESULT to the human operator's web dashboard (AMS /admin/).

    Call this after every finished piece of work (what was done, outcome,
    where the output is). Fire-and-forget: no answer is expected. NEVER put
    secrets, tokens or passwords in the body."""
    agent_id, api_key = _ensure_joined()
    return api.operator_post(agent_id, api_key, "report", body, title=title, task_id=task_id)


@mcp.tool()
def operator_status(
    body: str, title: str | None = None, task_id: str | None = None, ack: str | None = None
) -> dict:
    """Push a short PROGRESS/status line to the operator's web dashboard
    (e.g. "migrating step 2/5"). Fire-and-forget. No secrets in the body.

    ack (optional): when the human operator BROADCAST a message to you (its
    text ends with "[broadcast <id>] ..."), pass that <id> here to acknowledge
    it; the operator then sees that you received it. Ignored if the id is not
    one you were sent."""
    agent_id, api_key = _ensure_joined()
    if ack is not None:
        return api.operator_post(agent_id, api_key, "status", body, title=title, task_id=task_id, ack=ack)
    return api.operator_post(agent_id, api_key, "status", body, title=title, task_id=task_id)


@mcp.tool()
def operator_ask(question: str, title: str | None = None, task_id: str | None = None) -> dict:
    """Ask the human operator a QUESTION on the web dashboard and return
    immediately with {event_id, ...} (it does not block).

    IMPORTANT: ALSO ask the same question to the human in your own CLI/chat.
    The human can answer on the web OR in the CLI -- whichever answer comes
    FIRST wins. A web answer arrives in your inbox as a message starting with
    "[ANSWER to question <event_id>] ..." (treat it as the human's answer), or
    you can poll with operator_check_answer(event_id). If the human answers in
    the CLI instead, call operator_resolve(event_id, answer) so the web shows
    the question as answered. No secrets in the question."""
    agent_id, api_key = _ensure_joined()
    return api.operator_post(agent_id, api_key, "question", question, title=title, task_id=task_id)


@mcp.tool()
def operator_check_answer(event_id: str) -> dict:
    """Check a question asked with operator_ask. Returns the event; when
    status == "answered", `answer` and `answered_via` ("web" or "cli") are set."""
    agent_id, api_key = _ensure_joined()
    return api.operator_get(agent_id, api_key, event_id)


@mcp.tool()
def operator_resolve(event_id: str, answer: str) -> dict:
    """Record that the human answered question `event_id` in the CLI (not on
    the web), so the dashboard shows it as answered. Fails if it was already
    answered (the first answer wins -- use operator_check_answer to see it)."""
    agent_id, api_key = _ensure_joined()
    return api.operator_resolve(agent_id, api_key, event_id, answer)


@mcp.tool()
def agent_context() -> dict:
    """Ask AMS everything about YOURSELF: your agent_id, display_name, role,
    project, host_id, channel, parent_agent_id, capabilities, profile (null if
    none yet), the task currently assigned/claimed to you, your unread messages
    (count + ids/senders; reading this does NOT consume them), your address book
    and the reply rules.

    IMPORTANT: "system-dashboard" in the address book is the HUMAN OPERATOR (a
    person on the AMS web dashboard), NOT another AI agent. Returns only your
    own data. Call it whenever you are unsure who you are, what you are
    working on, or who to answer."""
    agent_id, api_key = _ensure_joined()
    return api.agent_context(agent_id, api_key)


@mcp.tool()
def agent_message_origin(message_id: str) -> dict:
    """Look up the ORIGINAL message with this message_id (one you sent or
    received) and who sent it: from_agent, sender_display_name and sender_kind.

    sender_kind == "operator" means from_agent is "system-dashboard", the
    HUMAN OPERATOR (a person) -> answer with operator_report / operator_status / operator_ask.
    sender_kind == "agent" means another AI agent -> answer with
    agent_send_message to that from_agent. Does not consume the message. An id
    that is unknown or not yours returns an error (it looks the same either way)."""
    agent_id, api_key = _ensure_joined()
    try:
        return api.message_origin(agent_id, api_key, message_id)
    except api.GatewayError:
        return {"error": f"message {message_id} not found"}


ONBOARDING_TEXT = """AMS (Agent Mesh) onboarding

WHO IS WHO
- You are an agent in the mesh. agent_context() tells you your role, project, task and unread messages.
- "system-dashboard" is the HUMAN OPERATOR: a real person on the AMS web dashboard. It is NOT an AI agent.
- Every other agent_id is another AI agent.

HOW TO REPLY
- Work that comes from AMS (a message from system-dashboard, or a task): answer the human with
  operator_report (final result), operator_status (progress line) or operator_ask (a question).
- A message from another agent: answer with agent_send_message to that message's from_agent.
- Always include task_id (when there is one) and in_reply_to (the message_id you are answering).
- Not sure who sent a message? agent_message_origin(message_id) returns sender_kind (operator or agent).

BROADCASTS
- If the operator broadcasts to all agents, the message ends with "[broadcast <id>]".
  Acknowledge with operator_status(body, ack="<id>").

NEVER put secrets, tokens or passwords in any message or report."""


@mcp.prompt(name="ams-onboarding")
def ams_onboarding_prompt() -> str:
    """Roles, reply rules and how to report in AMS (operator_report/status/ask)."""
    return ONBOARDING_TEXT


@mcp.resource("ams://onboarding", name="ams-onboarding")
def ams_onboarding_resource() -> str:
    """Roles, reply rules and how to report in AMS (operator_report/status/ask)."""
    return ONBOARDING_TEXT


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
