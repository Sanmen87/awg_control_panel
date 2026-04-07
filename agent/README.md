# AWG Panel Agent

Current direction and current implemented state for the per-server agent:

- installed automatically on every managed server together with AWG
- existing servers can install it later from the panel
- local traffic accounting while the panel is offline
- execution of server-local tasks queued by the panel
- deferred synchronization of local state and task results back to the panel
- optional future heartbeat and health/status reporting back to the control panel
- future reuse of the existing proxy failover logic on proxy nodes

The current backend and runtime now include:

- `AgentNode` for enrollment, token auth, heartbeat, and local state snapshots
- `AgentTask` as a server-local task journal
- local runtime daemon installed as:
  - `/usr/local/bin/awg-panel-agent.py`
  - `awg-panel-agent.service`
- local state paths:
  - `/var/lib/awg-panel/agent-status.json`
  - `/var/lib/awg-panel/agent-tasks/`
  - `/var/lib/awg-panel/agent-results/`
- user-side API for:
  - enrolling/regenerating an agent token for a server
  - listing enrolled agents
  - queueing agent tasks per server
  - installing the agent on an existing server
  - reading local agent status
  - syncing local agent results
- agent-side sync API for:
  - heartbeat
  - pulling pending tasks
  - acknowledging task results
- current allowlisted handlers:
  - `collect-runtime-snapshot`
  - `collect-traffic-counters`
  - `read-clients-table`
  - `inspect-standard-runtime`

Current hybrid mode:

- if `PANEL_PUBLIC_BASE_URL` is empty:
  - agent works in local-only mode
  - panel reaches it indirectly over SSH by reading status/results and dropping local tasks
- if `PANEL_PUBLIC_BASE_URL` is set later:
  - the same agent can use web sync endpoints

Security model:

- no arbitrary shell from panel API
- only allowlisted task handlers
- one token per server
- SSH remains the install/update transport
