from datetime import datetime

from pydantic import BaseModel

from app.models.topology import TopologyStatus, TopologyType


class TopologyBase(BaseModel):
    name: str
    type: TopologyType
    active_exit_server_id: int | None = None
    failover_config_json: str | None = None
    config_version: str | None = None


class TopologyCreate(TopologyBase):
    pass


class TopologyUpdate(BaseModel):
    name: str | None = None
    type: TopologyType | None = None
    active_exit_server_id: int | None = None
    failover_config_json: str | None = None
    config_version: str | None = None


class TopologyRead(TopologyBase):
    id: int
    status: TopologyStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
