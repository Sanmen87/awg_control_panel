from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ServiceInstance(Base, TimestampMixin):
    __tablename__ = "service_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_type: Mapped[str] = mapped_column(String(64), nullable=False)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="new")
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
