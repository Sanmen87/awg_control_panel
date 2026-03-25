import enum

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_utils import enum_values


class TopologyNodeRole(str, enum.Enum):
    STANDARD_VPN = "standard-vpn"
    PROXY = "proxy"
    EXIT = "exit"
    PROXY_SECONDARY = "proxy-secondary"


class TopologyNode(Base, TimestampMixin):
    __tablename__ = "topology_nodes"
    __table_args__ = (UniqueConstraint("topology_id", "server_id", name="uq_topology_server"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topology_id: Mapped[int] = mapped_column(ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[TopologyNodeRole] = mapped_column(
        Enum(TopologyNodeRole, name="topology_node_role", values_callable=enum_values),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
