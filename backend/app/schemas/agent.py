from datetime import datetime

from pydantic import BaseModel


class AgentEnrollRead(BaseModel):
    id: int
    server_id: int
    token: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentNodeRead(BaseModel):
    id: int
    server_id: int
    status: str
    version: str | None
    capabilities_json: str | None
    last_seen_at: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    local_state_json: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentTaskCreate(BaseModel):
    task_type: str
    payload_json: str | None = None


class AgentTaskRead(BaseModel):
    id: int
    agent_id: int
    server_id: int
    task_type: str
    status: str
    payload_json: str | None
    result_json: str | None
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentHeartbeatPayload(BaseModel):
    version: str | None = None
    capabilities_json: str | None = None
    local_state_json: str | None = None
    last_error: str | None = None


class AgentTaskAckPayload(BaseModel):
    status: str
    result_json: str | None = None
    last_error: str | None = None

