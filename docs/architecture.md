# Architecture Notes

## V1 building blocks

- FastAPI backend with REST API
- Next.js frontend with admin shell
- PostgreSQL for core state
- Redis and Celery for background jobs
- nginx as reverse proxy
- hybrid per-server agent for offline accounting, local task execution, deferred sync, and optional future web sync

## Initial domain entities

- `Server`
- `Topology`
- `TopologyNode`
- `Client`
- `User`
- `DeploymentJob`
- `BackupJob`
- `ServiceInstance`
- `FailoverEvent`
- `AuditLog`
- `AgentNode`
- `AgentTask`

Current hybrid agent already covers:

- SSH-driven install/update from the panel
- local status file
- local task queue
- local task result spool
- local policy snapshot and local policy state files for offline client enforcement
- optional future web sync if the panel later gets a public URL

Current hybrid agent direction also includes:

- offline client-policy enforcement on the server side:
  - traffic limits
  - expiration
  - quiet hours
- panel-side reconciliation of offline-collected policy state back into DB
- future per-peer bandwidth shaping through agent-managed `tc`, keyed by client `assigned_ip`

Future iterations will add:

- credentials vault abstractions
- AWG peer and config revision models
- topology deployment renderer
- backup archive inventory
- richer agent heartbeat and health snapshots in UI
- more read-only runtime flows moved from SSH to agent
- careful evaluation of which write paths may later move to agent
- explicit policy event journal and conflict resolution for offline enforcement
- reconcile-based peer bandwidth policy service
