from datetime import datetime

from pydantic import BaseModel


class EligibleServiceServerRead(BaseModel):
    id: int
    name: str
    host: str
    topology_name: str | None = None
    topology_role: str | None = None


class ExtraServiceCreate(BaseModel):
    service_type: str = "mtproxy"
    server_id: int
    domain: str | None = None


class ExtraServiceDeliveryRequest(BaseModel):
    email: str


class ExtraServiceRead(BaseModel):
    id: int
    service_type: str
    server_id: int
    server_name: str | None = None
    server_host: str | None = None
    topology_name: str | None = None
    topology_role: str | None = None
    status: str
    config_json: str | None = None
    runtime_details_json: str | None = None
    public_endpoint: str | None = None
    last_error: str | None = None
    install_job_id: int | None = None
    install_job_status: str | None = None
    install_job_task_id: str | None = None
    install_job_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
