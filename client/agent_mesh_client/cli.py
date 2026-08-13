import sys
import time

import click
import requests

from . import api, config, artifacts
from . import identity as identity_mod
from .heartbeat import HeartbeatThread


@click.group()
def cli():
    """agentctl - Claude Code Agent Mesh CLI."""


def _perform_join(role: str, display_name: str, domain: str, project: str | None):
    try:
        ident = identity_mod.build_identity(
            role=role, display_name=display_name, domain=domain, project=project
        )
    except ValueError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)
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
    "--once",
    is_flag=True,
    default=False,
    help=(
        "Register and start heartbeat, then exit immediately (for scripting/tests). "
        "Without this flag, join blocks in the foreground sending heartbeats every "
        "5s until interrupted with Ctrl+C -- use this mode to keep an agent ONLINE."
    ),
)
def join(role: str | None, display_name: str, domain: str, project: str | None, once: bool):
    # A gateway that is down, unreachable, or rejecting the join token is an
    # ordinary operational condition -- report it as a one-line error rather
    # than dumping a traceback at the user. build_identity() raising ValueError
    # for a missing role is handled the same way, inside _perform_join.
    try:
        data, heartbeat = _perform_join(role, display_name, domain, project)
    except (api.GatewayError, requests.RequestException) as exc:
        click.echo(f"Failed to join: {exc}", err=True)
        sys.exit(1)
    click.echo(f"Joined as {data['agent_id']} (status={data['status']})")
    if once:
        return
    click.echo("Sending heartbeat every 5s. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        heartbeat.stop()
        click.echo("Stopped.")


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
