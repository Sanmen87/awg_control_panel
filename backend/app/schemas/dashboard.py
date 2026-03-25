from datetime import datetime

from pydantic import BaseModel

from app.models.server import InstallMethod, ServerStatus


class ServerDashboardMetrics(BaseModel):
    cpu_percent: float
    memory_total_bytes: int
    memory_used_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    network_interface: str | None
    network_rx_rate_bps: float
    network_tx_rate_bps: float
    uptime_seconds: int
    load1: float
    load5: float
    load15: float
    container_status: str | None
    sampled_at: datetime | None


class DashboardServerItem(BaseModel):
    id: int
    name: str
    status: ServerStatus
    install_method: InstallMethod
    runtime_flavor: str | None
    awg_detected: bool
    metrics: ServerDashboardMetrics | None


class DashboardTopPeerItem(BaseModel):
    id: int
    name: str
    server_name: str | None
    runtime_connected: bool
    status: str
    total_30d_bytes: int
    rx_30d_bytes: int
    tx_30d_bytes: int


class DashboardClientsAccess(BaseModel):
    total: int
    active: int
    online: int
    imported: int
    generated: int
    manual_disabled: int
    policy_disabled: int
    expiring_3d: int
    expiring_7d: int


class DashboardSummary(BaseModel):
    api_status: str
    servers: list[DashboardServerItem]
    top_peers: list[DashboardTopPeerItem]
    clients_access: DashboardClientsAccess
