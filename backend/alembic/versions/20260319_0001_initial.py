"""initial schema"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260319_0001"
down_revision = None
branch_labels = None
depends_on = None


server_role = postgresql.ENUM("standard-vpn", "proxy", "exit", "proxy-secondary", name="server_role", create_type=False)
server_status = postgresql.ENUM("new", "healthy", "degraded", "error", name="server_status", create_type=False)
topology_type = postgresql.ENUM("standard", "proxy-exit", "proxy-multi-exit", name="topology_type", create_type=False)
topology_status = postgresql.ENUM("draft", "pending", "applied", "error", name="topology_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    server_role.create(bind, checkfirst=True)
    server_status.create(bind, checkfirst=True)
    topology_type.create(bind, checkfirst=True)
    topology_status.create(bind, checkfirst=True)

    op.create_table(
        "topologies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("type", topology_type, nullable=False),
        sa.Column("status", topology_status, nullable=False, server_default="draft"),
        sa.Column("active_exit_server_id", sa.Integer(), nullable=True),
        sa.Column("failover_config_json", sa.Text(), nullable=True),
        sa.Column("config_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(length=255), nullable=False),
        sa.Column("auth_method", sa.String(length=50), nullable=False, server_default="key"),
        sa.Column("role", server_role, nullable=False),
        sa.Column("status", server_status, nullable=False, server_default="new"),
        sa.Column("topology_id", sa.Integer(), nullable=True),
        sa.Column("config_version", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("public_key", sa.String(length=255), nullable=False),
        sa.Column("assigned_ip", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("topology_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("traffic_limit_mb", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("clients")
    op.drop_table("servers")
    op.drop_table("topologies")

    bind = op.get_bind()
    topology_status.drop(bind, checkfirst=True)
    topology_type.drop(bind, checkfirst=True)
    server_status.drop(bind, checkfirst=True)
    server_role.drop(bind, checkfirst=True)
