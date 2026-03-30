from datetime import datetime

from pydantic import BaseModel

from app.models.backup import BackupStatus, BackupType


class BackupJobCreate(BaseModel):
    backup_type: BackupType
    server_id: int | None = None


class BackupRestoreRequest(BaseModel):
    server_id: int | None = None
    bundle_server_id: int | None = None


class BackupJobRead(BaseModel):
    id: int
    backup_type: BackupType
    server_id: int | None
    status: BackupStatus
    storage_path: str | None
    result_message: str | None
    manifest_server_name: str | None = None
    manifest_server_host: str | None = None
    manifest_install_method: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BackupPreviewServerRead(BaseModel):
    server_id: int
    name: str | None = None
    host: str | None = None
    install_method: str | None = None
    runtime_flavor: str | None = None
    live_interface_name: str | None = None
    live_config_path: str | None = None
    clients_table_path: str | None = None
    has_clients_table: bool = False


class BackupPreviewRead(BaseModel):
    backup_type: str
    created_at: str | None = None
    panel_project_name: str | None = None
    has_panel_dump: bool = False
    servers: list[BackupPreviewServerRead] = []
