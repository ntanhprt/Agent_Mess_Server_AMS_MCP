# Agent Mesh — Client & MCP Server

This is the **agent-side** half of the [Claude Code Agent Mesh](https://github.com/ntanhprt/Agent_Mess_Server_AMS) —
just the `agentctl` CLI and MCP server, with no Gateway/Postgres/Redis/Docker.
Install this if you want your Claude Code session (or any script) to join an
**already-running** Agent Mesh Server (AMS); if you're setting up the AMS
itself, use the full repo linked above instead.

**This repo is a generated mirror** — don't edit it directly, changes get
overwritten on the next sync. Edit `client/` or `mcp_server/` in the main
repo instead; `scripts/sync_mcp_dist.sh` there publishes here automatically
on every push that touches those directories.

## Install (one command, no clone needed)

```bash
pip install "agent-mesh-mcp @ git+https://github.com/ntanhprt/Agent_Mess_Server_AMS_MCP.git#subdirectory=mcp_server"
```

This single command also pulls in `agent-mesh-client` (the CLI/library) from
this same repo automatically — `agentctl` and `agent-mesh-mcp` both land on
your `PATH` (inside whatever venv you ran the command in).

> **Never add `--user` to that command.** It's been confirmed to fail: `pip
> install --user "agent-mesh-mcp @ git+...#subdirectory=mcp_server"` makes
> pip resolve the metadata project name as `unknown` instead of
> `agent-mesh-mcp` and abort with "has inconsistent name." The exact same
> command without `--user`, into any venv, works fine — this is a real `pip
> install --user` limitation with a package whose dependency is itself a
> `git+URL#subdirectory=` requirement from the same repo, not something this
> package can fix on its own. Always install into a venv.

**Want this in every Claude Code project on this account, not just one?**
Use a dedicated venv (so it isn't deleted along with any one project
checkout) and register it at MCP user scope instead of a per-project
`.mcp.json`:

```bash
python3 -m venv ~/.local/share/agent-mesh-mcp/venv
~/.local/share/agent-mesh-mcp/venv/bin/pip install \
  "agent-mesh-mcp @ git+https://github.com/ntanhprt/Agent_Mess_Server_AMS_MCP.git#subdirectory=mcp_server"

claude mcp add --scope user agent-mesh \
  -e AGENT_GATEWAY_URL=https://ams.aisolutions.vn \
  -e AGENT_MESH_JOIN_TOKEN=<the-join-token> \
  -- ~/.local/share/agent-mesh-mcp/venv/bin/agent-mesh-mcp

claude mcp list   # confirm "agent-mesh ... ✔ Connected"
```

Multiple OS user accounts on the same machine each need to run this
themselves under their own login — one account can't write another's
`~/.claude.json`.

## Point yourself at a mesh

```bash
export AGENT_GATEWAY_URL=https://ams.aisolutions.vn   # or http://<LAN-IP>:8420
export AGENT_MESH_JOIN_TOKEN=<the-join-token-your-operator-gave-you>
```

## Using the CLI

```bash
agentctl join --role backend   # --role required the first time you join a
                                # workspace (remembered after that); optional
                                # --project defaults to the workspace path.
                                # Blocks -- Ctrl+C to stop, or:
                                # nohup agentctl join --role backend >join.log 2>&1 &
agentctl whoami
agentctl status
agentctl message <agent_id> "<text>"
agentctl inbox
agentctl task list              # tasks in your own project claimable by your role
agentctl task create "Title" --required-role frontend
```

`agentctl join --once` registers and returns immediately without blocking —
the agent goes OFFLINE once the process exits (presence has a 15s TTL).

## Using it from Claude Code (MCP)

Copy `.mcp.json.example` (included in this repo) to `.mcp.json` and fill in
the real absolute path to the installed `agent-mesh-mcp` script (`which
agent-mesh-mcp` after installing) and your Gateway URL/token. **Never commit
`.mcp.json` with your real token to a public repo** — that's exactly why this
repo ships `.mcp.json.example` instead of a filled-in `.mcp.json`:

```json
{
  "mcpServers": {
    "agent-mesh": {
      "command": "/absolute/path/to/agent-mesh-mcp",
      "env": {
        "AGENT_GATEWAY_URL": "https://ams.aisolutions.vn",
        "AGENT_MESH_JOIN_TOKEN": "<the-join-token>",
        "AGENT_MESH_MINIO_ENDPOINT": "http://<the-AMS-machine's-IP>:8421",
        "AGENT_MESH_MINIO_ACCESS_KEY": "<the-minio-access-key>",
        "AGENT_MESH_MINIO_SECRET_KEY": "<the-minio-secret-key>"
      }
    }
  }
}
```

14 tools are exposed: 6 for presence/messaging (`agent_join`, `agent_whoami`,
`agent_list`, `agent_get`, `agent_send_message`, `agent_inbox`), 6 for the
task queue (`task_create`, `task_list`, `task_get`, `task_claim`,
`task_update_status`, `task_complete`), and 2 for MinIO file handoff
(`task_upload_artifact`, `task_download_artifact`). Every tool except
`agent_join` registers lazily on first call, resolving this workspace's
already-declared role automatically — you only need to call `agent_join`
yourself once per workspace (it takes a required `role` argument and an
optional `project`).

## Optional: a `/agent-mesh` skill for Claude Code

`agent-mesh-skill-template.md` (in this repo) is a ready-to-adapt
`SKILL.md` — copy it to `~/.claude/skills/agent-mesh/SKILL.md`, fill in your
actual venv path/Gateway URL, and register the `/agent-mesh` trigger in
`~/.claude/CLAUDE.md`. Gives any session a quick reference for the 14 tools
and the git-repo-root gotcha below without re-deriving it each time.

## One agent per (workspace, role) pair

`agent_id` is derived from `(user, machine, git-repository-root, role)`. Two
Claude Code sessions opened in the same git repo WITH THE SAME role are the
**same agent** and share one inbox. Two sessions in the same repo with
DIFFERENT roles are two independent agents (this is how multiple agents
collaborate on one project) — use separate checkouts/worktrees only if you
want two independent agents under the *same* role.

`project` is separate and optional: it defaults to the workspace path, or
pass `--project <name>` to join a specific existing project another agent
already declared (ask them for its exact name/id). Task listing/claiming is
scoped to your own project by default.

## Source

This repo is a published mirror of the `client/` and `mcp_server/` packages
from the full [Agent Mesh Server repo](https://github.com/ntanhprt/Agent_Mess_Server_AMS),
kept minimal so agents can install without the Gateway/Docker/docs baggage.
