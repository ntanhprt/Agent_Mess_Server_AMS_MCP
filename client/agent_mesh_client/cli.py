import sys
import time

import click
import requests

from . import api, config
from . import identity as identity_mod
from .heartbeat import HeartbeatThread


@click.group()
def cli():
    """agentctl - Claude Code Agent Mesh CLI."""


def _perform_join():
    ident = identity_mod.build_identity()
    data = api.join(ident, capabilities=[])
    heartbeat = HeartbeatThread(data["agent_id"], data["api_key"])
    heartbeat.start()
    return data, heartbeat


@cli.command()
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
def join(once: bool):
    # A gateway that is down, unreachable, or rejecting the join token is an
    # ordinary operational condition -- report it as a one-line error rather
    # than dumping a traceback at the user.
    try:
        data, heartbeat = _perform_join()
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
    ident = identity_mod.build_identity()
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
