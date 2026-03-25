from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ClientRuntimeSample(Base):
    __tablename__ = "client_runtime_samples"
    __table_args__ = (
        Index("ix_client_runtime_samples_client_id_sampled_at", "client_id", "sampled_at"),
        Index("ix_client_runtime_samples_server_id_sampled_at", "server_id", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_connected: Mapped[bool] = mapped_column(nullable=False, default=False)
    rx_bytes_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tx_bytes_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rx_bytes_delta: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tx_bytes_delta: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
