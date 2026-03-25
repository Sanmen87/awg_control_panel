from datetime import datetime

from pydantic import BaseModel

from app.models.topology_node import TopologyNodeRole


class TopologyNodeBase(BaseModel):
    topology_id: int
    server_id: int
    role: TopologyNodeRole
    priority: int = 100
    status: str = "pending"


class TopologyNodeCreate(TopologyNodeBase):
    pass


class TopologyNodeUpdate(BaseModel):
    role: TopologyNodeRole | None = None
    priority: int | None = None
    status: str | None = None


class TopologyNodeRead(TopologyNodeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
