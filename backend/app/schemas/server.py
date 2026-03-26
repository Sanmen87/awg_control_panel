from datetime import datetime

from pydantic import BaseModel

from app.models.server import AWGStatus, AccessStatus, InstallMethod, ServerRole, ServerStatus


class ServerBase(BaseModel):
    host: str
    ssh_port: int = 22
    ssh_user: str
    auth_method: str = "key"
    role: ServerRole = ServerRole.STANDARD_VPN
    description: str | None = None
    topology_id: int | None = None
    config_version: str | None = None
    metadata_json: str | None = None


class ServerCreate(ServerBase):
    name: str | None = None
    install_method: InstallMethod = InstallMethod.DOCKER
    ssh_password: str | None = None
    ssh_private_key: str | None = None
    sudo_password: str | None = None


class ServerUpdate(BaseModel):
    name: str
    description: str | None = None


class ServerBootstrapRequest(BaseModel):
    install_method: InstallMethod | None = None


class ServerAwgProfileUpdate(BaseModel):
    profile_name: str
    apply_now: bool = True


class ServerRead(ServerBase):
    id: int
    name: str
    status: ServerStatus
    install_method: InstallMethod
    access_status: AccessStatus
    awg_status: AWGStatus
    os_name: str | None
    os_version: str | None
    awg_detected: bool
    awg_version: str | None
    runtime_flavor: str | None
    awg_interfaces_json: str | None
    config_source: str
    live_interface_name: str | None
    live_config_path: str | None
    live_address_cidr: str | None
    live_listen_port: int | None
    live_peer_count: int | None
    live_runtime_details_json: str | None
    host_metrics_json: str | None
    host_metrics_refreshed_at: datetime | None
    ready_for_topology: bool
    ready_for_managed_clients: bool = False
    topology_name: str | None = None
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
