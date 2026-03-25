from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ServerRuntimeSample(Base):
    __tablename__ = "server_runtime_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cpu_percent: Mapped[float] = mapped_column(nullable=False, default=0)
    memory_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    disk_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    disk_total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    network_rx_bytes_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    network_tx_bytes_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    network_rx_rate_bps: Mapped[float] = mapped_column(nullable=False, default=0)
    network_tx_rate_bps: Mapped[float] = mapped_column(nullable=False, default=0)
    uptime_seconds: Mapped[int] = mapped_column(nullable=False, default=0)
    load1: Mapped[float] = mapped_column(nullable=False, default=0)
    load5: Mapped[float] = mapped_column(nullable=False, default=0)
    load15: Mapped[float] = mapped_column(nullable=False, default=0)
