# Architecture Notes

## V1 building blocks

- FastAPI backend with REST API
- Next.js frontend with admin shell
- PostgreSQL for core state
- Redis and Celery for background jobs
- nginx as reverse proxy
- future per-server agent for offline accounting, local task execution, and deferred sync

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

Future iterations will add:

- credentials vault abstractions
- AWG peer and config revision models
- topology deployment renderer
- backup archive inventory
- agent heartbeat and health snapshots
- offline task journal between panel and per-server agent
