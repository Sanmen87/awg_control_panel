# Architecture Notes

## V1 building blocks

- FastAPI backend with REST API
- Next.js frontend with admin shell
- PostgreSQL for core state
- Redis and Celery for background jobs
- nginx as reverse proxy
- future Dockerized proxy agent for failover logic

## Initial domain entities

- `Server`
- `Topology`
- `TopologyNode`
- `Client`
- `User`
- `DeploymentJob`
- `BackupJob`
- `FailoverEvent`
- `AuditLog`

Future iterations will add:

- credentials vault abstractions
- AWG peer and config revision models
- topology deployment renderer
- backup archive inventory
- agent heartbeat and health snapshots
