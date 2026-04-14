from datetime import datetime

from pydantic import BaseModel, Field

from app.models.client import ClientSource


class ClientBase(BaseModel):
    name: str
    public_key: str
    assigned_ip: str
    status: str = "active"
    source: ClientSource = ClientSource.GENERATED
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
    import_note: str | None = None


class ClientCreate(ClientBase):
    private_key: str | None = None


class ManagedClientCreate(BaseModel):
    name: str
    server_id: int
    topology_id: int | None = None
    exit_server_id: int | None = None
    import_note: str | None = None
    expires_at: datetime | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_timezone: str | None = None
    traffic_limit_mb: int | None = None


class ClientUpdate(BaseModel):
    name: str
    status: str | None = None
    service_peer: bool | None = None
    exit_server_id: int | None = None
    import_note: str | None = None
    delivery_email: str | None = None
    delivery_telegram_chat_id: str | None = None
    delivery_telegram_username: str | None = None
    expires_at: datetime | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_timezone: str | None = None
    traffic_limit_mb: int | None = None


class ClientDeliveryRequest(BaseModel):
    channels: list[str] = Field(default_factory=list)


class ClientImportRequest(BaseModel):
    server_id: int


class ClientImportResponse(BaseModel):
    imported_count: int
    updated_count: int
    skipped_count: int
    client_ids: list[int]


class ClientMaterialsRead(BaseModel):
    ubuntu_config: str | None = None
    amneziawg_config: str | None = None
    amneziavpn_config: str | None = None
    qr_png_base64: str | None = None
    qr_png_base64_list: list[str] = Field(default_factory=list)
    amneziawg_qr_png_base64: str | None = None
    amneziawg_qr_png_base64_list: list[str] = Field(default_factory=list)
    amneziavpn_qr_png_base64: str | None = None
    amneziavpn_qr_png_base64_list: list[str] = Field(default_factory=list)


class ClientRead(ClientBase):
    id: int
    archived: bool = False
    service_peer: bool = False
    manual_disabled: bool = False
    private_key_available: bool
    materials_available: bool
    runtime_connected: bool
    latest_handshake_human: str | None = None
    data_received_human: str | None = None
    data_sent_human: str | None = None
    runtime_refreshed_at: datetime | None = None
    traffic_used_30d_rx_bytes: int = 0
    traffic_used_30d_tx_bytes: int = 0
    traffic_limit_exceeded_at: datetime | None = None
    policy_disabled_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
