import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_utils import enum_values


class TopologyType(str, enum.Enum):
    STANDARD = "standard"
    PROXY_EXIT = "proxy-exit"
    PROXY_MULTI_EXIT = "proxy-multi-exit"


class TopologyStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPLIED = "applied"
    ERROR = "error"


class Topology(Base, TimestampMixin):
    __tablename__ = "topologies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    type: Mapped[TopologyType] = mapped_column(
        Enum(TopologyType, name="topology_type", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[TopologyStatus] = mapped_column(
        Enum(TopologyStatus, name="topology_status", values_callable=enum_values),
        nullable=False,
        default=TopologyStatus.DRAFT,
    )
    active_exit_server_id: Mapped[int | None] = mapped_column(nullable=True)
    failover_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
