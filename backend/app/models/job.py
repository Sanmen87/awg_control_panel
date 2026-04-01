import enum

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_utils import enum_values


class JobType(str, enum.Enum):
    BOOTSTRAP_SERVER = "bootstrap-server"
    DEPLOY_TOPOLOGY = "deploy-topology"
    CHECK_SERVER = "check-server"
    DETECT_AWG = "detect-awg"
    INSTALL_EXTRA_SERVICE = "install-extra-service"
    BACKUP = "backup"
    RESTORE_SERVER = "restore-server"
    RESTORE_PANEL = "restore-panel"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DeploymentJob(Base, TimestampMixin):
    __tablename__ = "deployment_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, name="job_type", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=enum_values),
        nullable=False,
        default=JobStatus.PENDING,
    )
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    topology_id: Mapped[int | None] = mapped_column(ForeignKey("topologies.id", ondelete="SET NULL"), nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
