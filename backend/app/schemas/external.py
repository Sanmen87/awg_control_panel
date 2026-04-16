from datetime import datetime

from pydantic import BaseModel

from app.models.client import ClientSource
from app.models.server import AWGStatus, AccessStatus, InstallMethod, ServerRole, ServerStatus
from app.models.topology import TopologyStatus, TopologyType
from app.schemas.client import ClientMaterialsRead


class ExternalServerRead(BaseModel):
    id: int
    name: str
    host: str
    role: ServerRole
    status: ServerStatus
    install_method: InstallMethod
    access_status: AccessStatus
    awg_status: AWGStatus
    awg_detected: bool
    runtime_flavor: str | None = None
    live_interface_name: str | None = None
    live_address_cidr: str | None = None
    live_listen_port: int | None = None
    live_peer_count: int | None = None
    ready_for_topology: bool
    ready_for_managed_clients: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExternalClientRead(BaseModel):
    id: int
    name: str
    public_key: str
    assigned_ip: str
    status: str
    archived: bool = False
    service_peer: bool = False
    manual_disabled: bool = False
    source: ClientSource
    server_id: int | None = None
    topology_id: int | None = None
    exit_server_id: int | None = None
    delivery_email: str | None = None
    delivery_telegram_chat_id: str | None = None
    delivery_telegram_username: str | None = None
    expires_at: datetime | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_timezone: str | None = None
    traffic_limit_mb: int | None = None
    runtime_connected: bool
    latest_handshake_human: str | None = None
    data_received_human: str | None = None
    data_sent_human: str | None = None
    runtime_refreshed_at: datetime | None = None
    traffic_used_30d_rx_bytes: int = 0
    traffic_used_30d_tx_bytes: int = 0
    traffic_limit_exceeded_at: datetime | None = None
    policy_disabled_reason: str | None = None
    import_note: str | None = None
    private_key_available: bool
    materials_available: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExternalTopologyClientCreate(BaseModel):
    name: str
    exit_server_id: int | None = None
    import_note: str | None = None
    expires_at: datetime | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_timezone: str | None = None
    traffic_limit_mb: int | None = None
    delivery_email: str | None = None
    delivery_telegram_chat_id: str | None = None
    delivery_telegram_username: str | None = None


class ExternalExitTargetRead(BaseModel):
    server_id: int
    name: str
    host: str
    priority: int
    is_default: bool
    status: ServerStatus
    ready_for_managed_clients: bool


class ExternalClientTargetRead(BaseModel):
    topology_id: int
    topology_name: str
    topology_type: TopologyType
    topology_status: TopologyStatus
    create_server_id: int
    create_server_name: str
    create_server_host: str
    default_exit_server_id: int | None = None
    exit_servers: list[ExternalExitTargetRead]


class ExternalClientMaterialsRead(ClientMaterialsRead):
    pass


class ExternalClientCreateWithMaterialsRead(BaseModel):
    client: ExternalClientRead
    materials: ExternalClientMaterialsRead
