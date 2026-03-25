import asyncio
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.client import Client, ClientSource
from app.models.server import AccessStatus
from app.models.server import Server
from app.models.user import User
from app.schemas.dashboard import (
    DashboardClientsAccess,
    DashboardServerItem,
    DashboardSummary,
    DashboardTopPeerItem,
)
from app.services.server_metrics import ServerMetricsService

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DashboardSummary:
    servers = db.query(Server).order_by(Server.name.asc()).all()
    clients = db.query(Client).filter(Client.archived.is_(False)).order_by(Client.name.asc()).all()
    server_name_by_id = {server.id: server.name for server in servers}
    now = datetime.now(UTC)
    expiring_3d_cutoff = now + timedelta(days=3)
    expiring_7d_cutoff = now + timedelta(days=7)
    metrics_service = ServerMetricsService()

    for server in servers:
        is_stale = not server.host_metrics_refreshed_at or (now - server.host_metrics_refreshed_at) > timedelta(minutes=2)
        if server.access_status == AccessStatus.OK and is_stale:
            try:
                updated = asyncio.run(metrics_service.sync_server(db, server))
                if updated:
                    db.commit()
                    db.refresh(server)
            except Exception:
                db.rollback()

    dashboard_servers = []
    for server in servers:
        metrics = None
        if server.host_metrics_json:
            try:
                metrics_payload = json.loads(server.host_metrics_json)
            except json.JSONDecodeError:
                metrics_payload = {}
            metrics = {
                "cpu_percent": float(metrics_payload.get("cpu_percent") or 0),
                "memory_total_bytes": int(metrics_payload.get("memory_total_bytes") or 0),
                "memory_used_bytes": int(metrics_payload.get("memory_used_bytes") or 0),
                "disk_total_bytes": int(metrics_payload.get("disk_total_bytes") or 0),
                "disk_used_bytes": int(metrics_payload.get("disk_used_bytes") or 0),
                "network_interface": metrics_payload.get("network_interface") or None,
                "network_rx_rate_bps": float(metrics_payload.get("network_rx_rate_bps") or 0),
                "network_tx_rate_bps": float(metrics_payload.get("network_tx_rate_bps") or 0),
                "uptime_seconds": int(metrics_payload.get("uptime_seconds") or 0),
                "load1": float(metrics_payload.get("load1") or 0),
                "load5": float(metrics_payload.get("load5") or 0),
                "load15": float(metrics_payload.get("load15") or 0),
                "container_status": metrics_payload.get("container_status") or None,
                "sampled_at": server.host_metrics_refreshed_at,
            }
        dashboard_servers.append(
            DashboardServerItem(
                id=server.id,
                name=server.name,
                status=server.status,
                install_method=server.install_method,
                runtime_flavor=server.runtime_flavor,
                awg_detected=server.awg_detected,
                metrics=metrics,
            )
        )

    top_clients = sorted(
        clients,
        key=lambda client: client.traffic_used_30d_rx_bytes + client.traffic_used_30d_tx_bytes,
        reverse=True,
    )[:5]
    top_peers = [
        DashboardTopPeerItem(
            id=client.id,
            name=client.name,
            server_name=server_name_by_id.get(client.server_id),
            runtime_connected=client.runtime_connected,
            status=client.status,
            total_30d_bytes=client.traffic_used_30d_rx_bytes + client.traffic_used_30d_tx_bytes,
            rx_30d_bytes=client.traffic_used_30d_rx_bytes,
            tx_30d_bytes=client.traffic_used_30d_tx_bytes,
        )
        for client in top_clients
    ]

    expiring_3d = 0
    expiring_7d = 0
    for client in clients:
        if client.expires_at and client.expires_at >= now:
            if client.expires_at <= expiring_3d_cutoff:
                expiring_3d += 1
            if client.expires_at <= expiring_7d_cutoff:
                expiring_7d += 1

    return DashboardSummary(
        api_status="ok",
        servers=dashboard_servers,
        top_peers=top_peers,
        clients_access=DashboardClientsAccess(
            total=len(clients),
            active=sum(1 for client in clients if client.status == "active"),
            online=sum(1 for client in clients if client.runtime_connected),
            imported=sum(1 for client in clients if client.source == ClientSource.IMPORTED),
            generated=sum(1 for client in clients if client.source == ClientSource.GENERATED),
            manual_disabled=sum(1 for client in clients if client.manual_disabled),
            policy_disabled=sum(1 for client in clients if client.policy_disabled_reason is not None),
            expiring_3d=expiring_3d,
            expiring_7d=expiring_7d,
        ),
    )
