from datetime import datetime

from pydantic import BaseModel

from app.models.backup import BackupStatus, BackupType


class BackupJobCreate(BaseModel):
    backup_type: BackupType


class BackupJobRead(BaseModel):
    id: int
    backup_type: BackupType
    status: BackupStatus
    storage_path: str | None
    result_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

