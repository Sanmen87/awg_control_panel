import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_utils import enum_values


class BackupType(str, enum.Enum):
    DATABASE = "database"
    CONFIGS = "configs"
    FULL = "full"


class BackupStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BackupJob(Base, TimestampMixin):
    __tablename__ = "backup_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    backup_type: Mapped[BackupType] = mapped_column(
        Enum(BackupType, name="backup_type", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[BackupStatus] = mapped_column(
        Enum(BackupStatus, name="backup_status", values_callable=enum_values),
        nullable=False,
        default=BackupStatus.PENDING,
    )
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
