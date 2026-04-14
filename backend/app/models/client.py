import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_utils import enum_values


class ClientSource(str, enum.Enum):
    GENERATED = "generated"
    IMPORTED = "imported"


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    public_key: Mapped[str] = mapped_column(String(255), nullable=False)
    private_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    preshared_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    archived: Mapped[bool] = mapped_column(nullable=False, default=False)
    service_peer: Mapped[bool] = mapped_column(nullable=False, default=False)
    manual_disabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    source: Mapped[ClientSource] = mapped_column(
        Enum(ClientSource, name="client_source", values_callable=enum_values),
        nullable=False,
        default=ClientSource.GENERATED,
    )
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    topology_id: Mapped[int | None] = mapped_column(nullable=True)
    exit_server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    delivery_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_telegram_chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivery_telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quiet_hours_start_minute: Mapped[int | None] = mapped_column(nullable=True)
    quiet_hours_end_minute: Mapped[int | None] = mapped_column(nullable=True)
    quiet_hours_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    traffic_limit_mb: Mapped[int | None] = mapped_column(nullable=True)
    traffic_used_30d_rx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    traffic_used_30d_tx_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    traffic_limit_exceeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    policy_disabled_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    import_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_connected: Mapped[bool] = mapped_column(nullable=False, default=False)
    latest_handshake_human: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_received_human: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_sent_human: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runtime_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_ubuntu_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_amneziawg_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_amneziavpn_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_png_base64_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
