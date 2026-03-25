import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enum_utils import enum_values


class ServerRole(str, enum.Enum):
    STANDARD_VPN = "standard-vpn"
    PROXY = "proxy"
    EXIT = "exit"
    PROXY_SECONDARY = "proxy-secondary"


class ServerStatus(str, enum.Enum):
    NEW = "new"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"


class InstallMethod(str, enum.Enum):
    GO = "go"
    NATIVE = "native"
    DOCKER = "docker"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class AccessStatus(str, enum.Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class AWGStatus(str, enum.Enum):
    UNKNOWN = "unknown"
    DETECTED = "detected"
    MISSING = "missing"


class Server(Base, TimestampMixin):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    ssh_port: Mapped[int] = mapped_column(nullable=False, default=22)
    ssh_user: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(50), nullable=False, default="key")
    install_method: Mapped[InstallMethod] = mapped_column(
        Enum(InstallMethod, name="install_method", values_callable=enum_values),
        nullable=False,
        default=InstallMethod.UNKNOWN,
    )
    role: Mapped[ServerRole] = mapped_column(
        Enum(ServerRole, name="server_role", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[ServerStatus] = mapped_column(
        Enum(ServerStatus, name="server_status", values_callable=enum_values),
        nullable=False,
        default=ServerStatus.NEW,
    )
    topology_id: Mapped[int | None] = mapped_column(nullable=True)
    config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_flavor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ssh_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_private_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    sudo_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    os_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_status: Mapped[AccessStatus] = mapped_column(
        Enum(AccessStatus, name="access_status", values_callable=enum_values),
        nullable=False,
        default=AccessStatus.PENDING,
    )
    awg_status: Mapped[AWGStatus] = mapped_column(
        Enum(AWGStatus, name="awg_status", values_callable=enum_values),
        nullable=False,
        default=AWGStatus.UNKNOWN,
    )
    awg_detected: Mapped[bool] = mapped_column(nullable=False, default=False)
    awg_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    awg_interfaces_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_source: Mapped[str] = mapped_column(String(50), nullable=False, default="generated")
    live_interface_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    live_config_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    live_address_cidr: Mapped[str | None] = mapped_column(String(128), nullable=True)
    live_listen_port: Mapped[int | None] = mapped_column(nullable=True)
    live_peer_count: Mapped[int | None] = mapped_column(nullable=True)
    live_runtime_details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_metrics_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_for_topology: Mapped[bool] = mapped_column(nullable=False, default=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
