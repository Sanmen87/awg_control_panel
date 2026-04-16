from datetime import datetime

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: int
    user_id: int | None
    actor_type: str = "admin_user"
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    resource_type: str
    resource_id: str | None
    details: str | None
    metadata_json: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
