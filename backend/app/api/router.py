from fastapi import APIRouter

from app.api.v1.endpoints import auth, backups, clients, dashboard, health, jobs, logs, servers, settings, topology_nodes, topologies

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(servers.router, prefix="/servers", tags=["servers"])
api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
api_router.include_router(topologies.router, prefix="/topologies", tags=["topologies"])
api_router.include_router(topology_nodes.router, prefix="/topology-nodes", tags=["topology-nodes"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(backups.router, prefix="/backups", tags=["backups"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])
