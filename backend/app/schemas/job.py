from datetime import datetime

from pydantic import BaseModel, model_validator

from app.models.job import JobStatus, JobType


class DeploymentJobCreate(BaseModel):
    job_type: JobType
    server_id: int | None = None
    topology_id: int | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "DeploymentJobCreate":
        requires_server = self.job_type in {JobType.BOOTSTRAP_SERVER, JobType.CHECK_SERVER, JobType.DETECT_AWG}
        requires_topology = self.job_type == JobType.DEPLOY_TOPOLOGY
        if requires_server and not self.server_id:
            raise ValueError("server_id is required for this job type")
        if requires_topology and not self.topology_id:
            raise ValueError("topology_id is required for this job type")
        return self


class DeploymentJobRead(BaseModel):
    id: int
    job_type: JobType
    status: JobStatus
    server_id: int | None
    topology_id: int | None
    requested_by_user_id: int | None
    result_message: str | None
    task_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
