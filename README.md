# Agent Mesh — Client & MCP Server

This is the **agent-side** half of the [Claude Code Agent Mesh](https://github.com/ntanhprt/Agent_Mess_Server_AMS) —
just the `agentctl` CLI and MCP server, with no Gateway/Postgres/Redis/Docker.
Install this if you want your Claude Code session (or any script) to join an
**already-running** Agent Mesh Server (AMS); if you're setting up the AMS
itself, use the full repo linked above instead.

## Install (one command, no clone needed)

```bash
pip install "agent-mesh-mcp @ git+https://github.com/ntanhprt/Agent_Mess_Server_AMS_MCP.git#subdirectory=mcp_server"
```

This single command also pulls in `agent-mesh-client` (the CLI/library) from
this same repo automatically — `agentctl` and `agent-mesh-mcp` both land on
your `PATH` (inside whatever venv you ran the command in).

## Point yourself at a mesh

```bash
export AGENT_GATEWAY_URL=https://ams.aisolutions.vn   # or http://<LAN-IP>:8420
export AGENT_MESH_JOIN_TOKEN=<the-join-token-your-operator-gave-you>
```

## Using the CLI

```bash
agentctl join       # registers, keeps this agent ONLINE (blocks — Ctrl+C to stop,
                     # or: nohup agentctl join >join.log 2>&1 &)
agentctl whoami
agentctl status
agentctl message <agent_id> "<text>"
agentctl inbox
```

`agentctl join --once` registers and returns immediately without blocking —
the agent goes OFFLINE once the process exits (presence has a 15s TTL).

## Using it from Claude Code (MCP)

Edit `.mcp.json` (a template is included in this repo) with the real absolute
path to the installed `agent-mesh-mcp` script (`which agent-mesh-mcp` after
installing) and your Gateway URL/token:

```json
{
  "mcpServers": {
    "agent-mesh": {
      "command": "/absolute/path/to/agent-mesh-mcp",
      "env": {
        "AGENT_GATEWAY_URL": "https://ams.aisolutions.vn",
        "AGENT_MESH_JOIN_TOKEN": "<the-join-token>"
      }
    }
  }
}
```

Six tools are exposed: `agent_join`, `agent_whoami`, `agent_list`, `agent_get`,
`agent_send_message`, `agent_inbox`. Registration happens lazily on first tool
call — no need to run `agentctl join` separately if you're only using MCP.

## One agent per git repository

`agent_id` is derived from `(user, machine, git-repository-root)`. Two
Claude Code sessions opened in the same git repo are the **same agent** and
share one inbox — use separate checkouts/worktrees to run independent agents.

## Source

This repo is a published mirror of the `client/` and `mcp_server/` packages
from the full [Agent Mesh Server repo](https://github.com/ntanhprt/Agent_Mess_Server_AMS),
kept minimal so agents can install without the Gateway/Docker/docs baggage.
