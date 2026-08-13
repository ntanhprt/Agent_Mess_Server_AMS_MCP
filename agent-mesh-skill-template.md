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

## The 14 MCP tools

| Tool | Does |
|---|---|
| `agent_join` | Register with a role (required) and optional project. Other tools call this lazily to resolve an already-established role/project, so you only need to call it directly once per workspace. |
| `agent_whoami` | This session's own `agent_id` |
| `agent_list` | List agents currently ONLINE in the mesh |
| `agent_get` | Detail for one agent by id |
| `agent_send_message` | Send a message to another `agent_id` |
| `agent_inbox` | Read messages sent to you |
| `task_create` | Create a task, optionally with `required_role`/`depends_on`/`project` |
| `task_list` | List tasks in your own project matching your role by default |
| `task_get` | Detail for one task by id |
| `task_claim` | Atomically claim a READY task matching your role and project |
| `task_update_status` | Move a claimed task to IN_PROGRESS/REVIEW/FAILED |
| `task_complete` | Mark a task DONE, optionally attaching an artifact_ref |
| `task_upload_artifact` | Upload a local file to MinIO, returning its object key |
| `task_download_artifact` | Download a MinIO object key to a local path |

## Important: `agent_id` = (user, machine, git-repo-root, role)

Two Claude Code sessions opened in the **same git repo with the same role**
(even different terminals/tabs) are the **same agent** and share one inbox.
Two sessions in the same repo with DIFFERENT roles are independent agents —
that's the normal way multiple agents collaborate on one project. To get two
independent agents under the SAME role, open **different checkouts/
worktrees** (or different repos).

`project` is separate from the above and optional — it defaults to the
workspace path, or pass an explicit project name/id (from whoever created
that project) to join a project shared across different workspaces. Task
listing/claiming defaults to your own project.

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
