import sys
import time

import click
import requests

from . import api, config, artifacts, poller, state
from . import identity as identity_mod
from .heartbeat import HeartbeatThread


@click.group()
def cli():
    """agentctl - Claude Code Agent Mesh CLI."""


def _perform_join(
    role: str, display_name: str, domain: str, project: str | None, enroll_code: str | None = None
):
    try:
        ident = identity_mod.build_identity(
            role=role, display_name=display_name, domain=domain, project=project
        )
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    if enroll_code:
        data = api.join(ident, capabilities=[], enroll_code=enroll_code)
    else:
        data = api.join(ident, capabilities=[])
    heartbeat = HeartbeatThread(data["agent_id"], data["api_key"])
    heartbeat.start()
    return data, heartbeat


@cli.command()
@click.option("--role", default=None, help="Required the first time you join this workspace.")
@click.option("--display-name", default="", help="Optional human-friendly name.")
@click.option("--domain", default="", help="Optional description of what part of the project this agent covers.")
@click.option(
    "--project",
    default=None,
    help=(
        "Declare or join a named project. Omit to default to this workspace's "
        "path. To work in an EXISTING project another agent already declared, "
        "pass that exact same project name/id here."
    ),
)
@click.option(
    "--enroll-code",
    default=None,
    help=(
        "One-time enrollment code issued by the operator (or env AGENT_MESH_ENROLL_CODE). "
        "Needed when the gateway has the shared join token disabled."
    ),
)
@click.option(
    "--with-inbox",
    is_flag=True,
    default=False,
    help=(
        "After joining, also POLL the inbox (needed when the gateway cannot push into this "
        "host): new messages are printed and appended to ~/.agent-mesh/inbox/<agent_id>.jsonl; "
        "queued reports are flushed; a lost session is re-joined automatically."
    ),
)
@click.option("--poll-interval", type=int, default=60, show_default=True, help="Seconds between inbox polls.")
@click.option(
    "--once",
    is_flag=True,
    default=False,
    help=(
        "Register and start heartbeat, then exit immediately (for scripting/tests). "
        "Without this flag, join blocks in the foreground sending heartbeats every "
        "5s until interrupted with Ctrl+C -- use this mode to keep an agent ONLINE."
    ),
)
def join(
    role: str | None,
    display_name: str,
    domain: str,
    project: str | None,
    enroll_code: str | None,
    with_inbox: bool,
    poll_interval: int,
    once: bool,
):
    # A gateway that is down, unreachable, or rejecting the join token is an
    # ordinary operational condition -- report it as a one-line error rather
    # than dumping a traceback at the user. build_identity() raising ValueError
    # for a missing role is handled the same way, inside _perform_join.
    try:
        data, heartbeat = _perform_join(role, display_name, domain, project, enroll_code)
    except (api.GatewayError, requests.RequestException) as exc:
        click.echo(f"Failed to join: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Joined as {data['agent_id']} (status={data['status']})")
    _echo_resume(data["agent_id"])
    if once:
        return
    if with_inbox:
        click.echo(f"Sending heartbeat every 5s and polling the inbox every {poll_interval}s. Ctrl+C to stop.")
        _run_poller(data, heartbeat, role, display_name, domain, project, enroll_code, poll_interval)
        return
    click.echo("Sending heartbeat every 5s. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        heartbeat.stop()
        click.echo("Stopped.")


def _echo_new(msgs: list[dict]) -> None:
    for m in msgs:
        click.echo(
            f"[{m.get('created_at')}] {m.get('from_agent')} (message_id={m.get('message_id')}, "
            f"task_id={m.get('task_id')}): {m.get('body')}"
        )


def _run_poller(data, heartbeat, role, display_name, domain, project, enroll_code, interval):
    holder = {"hb": heartbeat}

    def rejoin():
        d, hb = _perform_join(role, display_name, domain, project, enroll_code)
        holder["hb"].stop()
        holder["hb"] = hb
        return d["agent_id"], d["api_key"]

    try:
        poller.run(data["agent_id"], data["api_key"], max(5, interval), _echo_new, rejoin=rejoin)
    except KeyboardInterrupt:
        holder["hb"].stop()
        click.echo("Stopped.")


@cli.command()
@click.option("--interval", type=int, default=60, show_default=True, help="Seconds between polls.")
@click.option("--once", is_flag=True, default=False, help="Poll one time and exit (for cron / schedulers).")
def poll(interval: int, once: bool):
    """Pull the inbox (no push needed): print NEW messages oldest first, append them to
    ~/.agent-mesh/inbox/<agent_id>.jsonl, ack them and flush queued reports. Use --once from
    cron/a scheduler, or without it as a foreground loop next to `agentctl join`."""
    agent_id, api_key = _current_identity()
    if once:
        try:
            poller.flush_outbox(agent_id, api_key)
            new = poller.poll_once(agent_id, api_key)
        except (api.GatewayError, requests.RequestException) as exc:
            click.echo(f"Poll failed: {exc}", err=True)
            sys.exit(1)
        _echo_new(new)
        if not new:
            click.echo("No new messages.")
        return
    try:
        poller.run(agent_id, api_key, max(5, interval), _echo_new)
    except KeyboardInterrupt:
        click.echo("Stopped.")


def _echo_resume(agent_id: str) -> None:
    """After a (re)join, show unfinished work saved by `agentctl checkpoint` so the agent
    (or its human) can pick up exactly where a crash/power loss/restart left off."""
    cp = state.load_checkpoint(agent_id)
    if not cp:
        return
    click.echo("Resuming unfinished work from the local checkpoint:")
    click.echo(f"  task_id : {cp.get('task_id') or '-'}")
    click.echo(f"  note    : {cp.get('note') or '-'}")
    for d in cp.get("docs") or []:
        click.echo(f"  doc     : {d}")
    click.echo(f"  saved   : {cp.get('updated_at', '?')}")


def _current_identity():
    try:
        ident = identity_mod.build_identity()
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
    api_key = config.get_api_key(ident["agent_id"])
    if not api_key:
        click.echo("Not joined yet. Run `agentctl join` first.", err=True)
        sys.exit(1)
    return ident["agent_id"], api_key


@cli.group()
def checkpoint():
    """Save/show/clear the unfinished-work checkpoint (survives restarts and power loss).
    Store task ids and file paths/notes only -- never secrets."""


@checkpoint.command("set")
@click.option("--task-id", default=None, help="The task being worked on.")
@click.option("--note", default=None, help="Where you are / what is next.")
@click.option("--doc", "docs", multiple=True, help="Repeatable: path/ref of a draft or document in progress.")
def checkpoint_set(task_id, note, docs):
    agent_id, _ = _current_identity()
    cp = state.save_checkpoint(agent_id, task_id=task_id, note=note, docs=list(docs))
    click.echo(f"Checkpoint saved ({cp['updated_at']})")


@checkpoint.command("show")
def checkpoint_show():
    agent_id, _ = _current_identity()
    cp = state.load_checkpoint(agent_id)
    if not cp:
        click.echo("No checkpoint.")
        return
    _echo_resume(agent_id)


@checkpoint.command("clear")
def checkpoint_clear():
    """Call when the work is finished."""
    agent_id, _ = _current_identity()
    click.echo("Checkpoint cleared." if state.clear_checkpoint(agent_id) else "No checkpoint.")


@cli.command()
def whoami():
    agent_id, api_key = _current_identity()
    click.echo(api.whoami(agent_id, api_key))


@cli.command()
def status():
    agent_id, api_key = _current_identity()
    for agent in api.list_agents(agent_id, api_key):
        click.echo(f"{agent['agent_id']:20s} {agent['status']:8s} {agent['workspace']}")


@cli.command()
@click.argument("to")
@click.argument("body")
def message(to: str, body: str):
    agent_id, api_key = _current_identity()
    click.echo(api.send_message(agent_id, api_key, to, body))


@cli.command()
def inbox():
    agent_id, api_key = _current_identity()
    for msg in api.inbox(agent_id, api_key):
        click.echo(f"[{msg['created_at']}] {msg['from_agent']}: {msg['body']}")


@cli.command()
def listen():
    """Giữ tiến trình sống, in ra tin nhắn NGAY khi AMS đẩy tới (SSE push) --
    thay cho việc phải tự gọi `agentctl inbox` lặp lại theo timer. Ctrl+C để dừng."""
    agent_id, api_key = _current_identity()
    click.echo(f"Listening for messages to {agent_id} (Ctrl+C to stop)...")

    def on_message(msg: dict) -> None:
        click.echo(f"[{msg['created_at']}] {msg['from_agent']}: {msg['body']}")

    try:
        api.listen_inbox(agent_id, api_key, on_message)
    except KeyboardInterrupt:
        click.echo("Stopped.")


@cli.command("log-work")
@click.argument("title")
@click.option("--detail", default=None, help="Chi tiết đầy đủ hơn (nhiều dòng OK).")
def log_work(title: str, detail: str | None):
    """Ghi nhận 1 đầu việc đã hoàn thành vào Lịch làm việc (worklog).

    Xuất hiện trên calendar AMS + được daily summary gom lại cuối ngày."""
    agent_id, api_key = _current_identity()
    click.echo(api.log_work(agent_id, api_key, title, detail=detail))


@cli.command("set-openproject-scope")
@click.argument("project_ids", nargs=-1, required=True)
def set_openproject_scope_cmd(project_ids: tuple[str, ...]):
    """Khai báo (các) project OpenProject agent này muốn daily summary tra để
    tìm việc "ngày mai" -- vd `agentctl set-openproject-scope 26 kbac`."""
    agent_id, api_key = _current_identity()
    click.echo(api.set_openproject_scope(agent_id, api_key, list(project_ids)))


@cli.group()
def task():
    """Manage tasks in the mesh's task queue."""


@task.command("create")
@click.argument("title")
@click.option("--description", default=None)
@click.option("--project", default=None, help="Create in a different project than your own (default: your declared project).")
@click.option("--required-role", default=None)
@click.option("--input-ref", default=None)
@click.option("--priority", default="normal")
@click.option("--depends-on", multiple=True, help="Repeatable: a task_id this task depends on.")
def task_create(title, description, project, required_role, input_ref, priority, depends_on):
    agent_id, api_key = _current_identity()
    result = api.create_task(
        agent_id,
        api_key,
        title,
        description=description,
        project=project,
        required_role=required_role,
        input_ref=input_ref,
        priority=priority,
        depends_on=list(depends_on),
    )
    click.echo(result)


@task.command("list")
@click.option("--status", default=None)
@click.option("--required-role", default=None)
@click.option("--project", default=None, help="List a different project's tasks (default: your own).")
def task_list_cmd(status, required_role, project):
    agent_id, api_key = _current_identity()
    for t in api.list_tasks(agent_id, api_key, status=status, required_role=required_role, project=project):
        click.echo(f"{t['task_id']}  {t['status']:12s} {t['title']}")


@task.command("get")
@click.argument("task_id")
def task_get_cmd(task_id):
    agent_id, api_key = _current_identity()
    click.echo(api.get_task(agent_id, api_key, task_id))


@task.command("claim")
@click.argument("task_id")
def task_claim_cmd(task_id):
    agent_id, api_key = _current_identity()
    try:
        click.echo(api.claim_task(agent_id, api_key, task_id))
    except api.GatewayError as exc:
        click.echo(f"Failed to claim task: {exc}", err=True)
        sys.exit(1)


@task.command("update")
@click.argument("task_id")
@click.argument("status")
@click.option("--note", default=None)
def task_update_cmd(task_id, status, note):
    agent_id, api_key = _current_identity()
    click.echo(api.update_task_status(agent_id, api_key, task_id, status, note=note))


@task.command("complete")
@click.argument("task_id")
@click.argument("summary")
@click.option("--artifact-ref", default=None, help="An already-uploaded object key.")
@click.option("--artifact-file", default=None, help="A local file to upload first; its resulting key is used as artifact_ref.")
def task_complete_cmd(task_id, summary, artifact_ref, artifact_file):
    agent_id, api_key = _current_identity()
    if artifact_file:
        artifact_ref = artifacts.upload_artifact(artifact_file, task_id)
    click.echo(api.complete_task(agent_id, api_key, task_id, summary, artifact_ref=artifact_ref))


@task.command("download-artifact")
@click.argument("object_key")
@click.argument("dest_path")
def task_download_artifact_cmd(object_key, dest_path):
    artifacts.download_artifact(object_key, dest_path)
    click.echo(f"Downloaded {object_key} -> {dest_path}")


def _operator_post_or_exit(kind: str, body: str, title: str | None, task_id: str | None) -> dict:
    agent_id, api_key = _current_identity()
    try:
        return api.operator_post(agent_id, api_key, kind, body, title=title, task_id=task_id)
    except (requests.ConnectionError, requests.Timeout) as exc:
        if kind in ("report", "status"):  # gateway unreachable: keep it; poll / join --with-inbox flushes it
            n = state.outbox_add(agent_id, kind, body, title, task_id)
            click.echo(f"Gateway unreachable ({exc}); queued locally ({n} pending), will be sent on reconnect.")
            sys.exit(0)
        click.echo(f"Failed to send to the operator channel: {exc}", err=True)
        sys.exit(1)
    except (api.GatewayError, requests.RequestException) as exc:
        click.echo(f"Failed to send to the operator channel: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("text")
@click.option("--title", default=None, help="Short headline shown on the web dashboard.")
@click.option("--task-id", default=None, help="Related task id, if any.")
def report(text: str, title: str | None, task_id: str | None):
    """Push a result/report to the web dashboard for the operator to follow.
    Never include secrets, tokens or passwords."""
    ev = _operator_post_or_exit("report", text, title, task_id)
    click.echo(f"Reported (event {ev['event_id']})")


@cli.command("status-update")
@click.argument("text")
@click.option("--title", default=None)
@click.option("--task-id", default=None)
def status_update(text: str, title: str | None, task_id: str | None):
    """Push a short progress/status line to the web dashboard."""
    ev = _operator_post_or_exit("status", text, title, task_id)
    click.echo(f"Status sent (event {ev['event_id']})")


@cli.command()
@click.argument("question")
@click.option("--title", default=None)
@click.option("--task-id", default=None)
@click.option(
    "--wait",
    type=int,
    default=0,
    help="Poll up to this many seconds for the answer (web or CLI, first wins).",
)
def ask(question: str, title: str | None, task_id: str | None, wait: int):
    """Ask the operator a question on the web dashboard. Prints the event id;
    with --wait, polls every 3s until it is answered or the timeout passes."""
    agent_id, api_key = _current_identity()
    ev = _operator_post_or_exit("question", question, title, task_id)
    event_id = ev["event_id"]
    click.echo(f"Question sent (event {event_id})")
    if wait <= 0:
        return
    deadline = time.monotonic() + wait
    while True:
        try:
            current = api.operator_get(agent_id, api_key, event_id)
        except (api.GatewayError, requests.RequestException) as exc:
            click.echo(f"Failed to check the answer: {exc}", err=True)
            sys.exit(1)
        if current["status"] == "answered":
            click.echo(f"Answer ({current['answered_via']}): {current['answer']}")
            return
        if time.monotonic() >= deadline:
            click.echo(f"No answer yet after {wait}s (event {event_id})", err=True)
            sys.exit(2)
        time.sleep(min(3, max(0.0, deadline - time.monotonic())))


@cli.command()
@click.argument("event_id")
@click.argument("answer")
def resolve(event_id: str, answer: str):
    """Record on the web dashboard that you answered question EVENT_ID here in
    the CLI, so the web shows it as answered."""
    agent_id, api_key = _current_identity()
    try:
        api.operator_resolve(agent_id, api_key, event_id, answer)
    except (api.GatewayError, requests.RequestException) as exc:
        click.echo(f"Failed to resolve: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Resolved {event_id}")
