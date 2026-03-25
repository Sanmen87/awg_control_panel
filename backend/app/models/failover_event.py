from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FailoverEvent(Base, TimestampMixin):
    __tablename__ = "failover_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    topology_id: Mapped[int] = mapped_column(ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False)
    previous_exit_server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    new_exit_server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False, default="agent")

