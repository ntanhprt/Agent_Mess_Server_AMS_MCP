---
name: agent-mesh
description: Message / check status of other Claude Code sessions (different repo, different OS account on this machine) via the Agent Mesh Server (AMS). Trigger /agent-mesh.
trigger: /agent-mesh
---

# /agent-mesh

This account's Claude Code sessions are connected to an **Agent Mesh Server (AMS)** —
a way for Claude Code sessions (different windows, different repos, different
OS accounts on this machine) to see each other and send messages, built at
`github.com/ntanhprt/Agent_Mess_Server_AMS`.

<!--
  TEMPLATE — copy this file to ~/.claude/skills/agent-mesh/SKILL.md and fill
  in the <PLACEHOLDER> values below for the account/venv you actually set up
  (see README.md § "Want this available in every Claude Code project" for
  the install steps that produce these values). Then register the trigger
  in ~/.claude/CLAUDE.md the same way this account's other skills are:

    # agent-mesh
    - **agent-mesh** (`~/.claude/skills/agent-mesh/SKILL.md`) - <one-line description>. Trigger: `/agent-mesh`
    When the user types `/agent-mesh`, invoke the Skill tool with `skill: "agent-mesh"` before doing anything else.
-->

## Installed at

- Package (`agent-mesh-mcp` + `agent-mesh-client`) in a dedicated venv, NOT
  via `pip install --user` (that hits a real pip bug resolving this
  package's git+subdirectory dependency chain — always use a venv):
  `<ABSOLUTE_PATH_TO_VENV>` (e.g. `/home/<user>/.local/share/agent-mesh-mcp/venv/`)
- MCP server registered at **user scope** (`claude mcp add --scope user`) —
  active in **every project** under this OS account, not just one repo:
  ```bash
  claude mcp get agent-mesh          # view current config
  claude mcp remove agent-mesh -s user   # remove if needed
  ```
- Pointed at the Gateway running at `<AGENT_GATEWAY_URL>` (e.g.
  `http://localhost:8420` or `https://ams.aisolutions.vn`), join token from
  whoever operates that AMS.
- **Other OS accounts on this machine are not configured** — each one needs
  to run the same `claude mcp add --scope user ...` under its own login;
  `~/.claude.json` is per-account and can't be written cross-account.

## The 6 MCP tools

| Tool | Does |
|---|---|
| `agent_join` | Register/refresh presence (ONLINE, 15s TTL). Other tools call this lazily, so you rarely need to call it directly. |
| `agent_whoami` | This session's own `agent_id` |
| `agent_list` | List agents currently ONLINE in the mesh |
| `agent_get` | Detail for one agent by id |
| `agent_send_message` | Send a message to another `agent_id` |
| `agent_inbox` | Read messages sent to you |

## Important: `agent_id` = (user, machine, git-repo-root)

Two Claude Code sessions opened in the **same git repo** (even different
terminals/tabs) are the **same agent** and share one inbox. To get two
independent agents that can message each other, open **different
checkouts/worktrees** (or different repos) — not just two tabs in the same
directory.

## Using the CLI (`agentctl`) instead of Claude Code tools

```bash
export AGENT_GATEWAY_URL=<AGENT_GATEWAY_URL>
export AGENT_MESH_JOIN_TOKEN=<JOIN_TOKEN>
<ABSOLUTE_PATH_TO_VENV>/bin/agentctl whoami
<ABSOLUTE_PATH_TO_VENV>/bin/agentctl status
<ABSOLUTE_PATH_TO_VENV>/bin/agentctl message <agent_id> "<text>"
<ABSOLUTE_PATH_TO_VENV>/bin/agentctl inbox
```

## Operating the AMS Gateway itself (only if you're also its operator)

If the Gateway (Postgres + Redis + FastAPI) runs on this machine too, it's
managed via `docker-compose.yml` in the AMS repo (`./ams.sh
start|stop|restart|status|logs`). Don't restart it without checking whether
other agents currently have this mesh open — ask first.
