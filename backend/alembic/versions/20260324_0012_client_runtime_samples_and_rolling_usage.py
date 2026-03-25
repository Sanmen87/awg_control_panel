"""client runtime samples and rolling usage

Revision ID: 20260324_0012
Revises: 20260324_0011
Create Date: 2026-03-24 16:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0012"
down_revision = "20260324_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("traffic_used_30d_rx_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("traffic_used_30d_tx_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("traffic_limit_exceeded_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("clients", "traffic_used_30d_rx_bytes", server_default=None)
    op.alter_column("clients", "traffic_used_30d_tx_bytes", server_default=None)

    op.create_table(
        "client_runtime_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_handshake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_connected", sa.Boolean(), nullable=False),
        sa.Column("rx_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("tx_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("rx_bytes_delta", sa.BigInteger(), nullable=False),
        sa.Column("tx_bytes_delta", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_runtime_samples_client_id_sampled_at",
        "client_runtime_samples",
        ["client_id", "sampled_at"],
        unique=False,
    )
    op.create_index(
        "ix_client_runtime_samples_server_id_sampled_at",
        "client_runtime_samples",
        ["server_id", "sampled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_client_runtime_samples_server_id_sampled_at", table_name="client_runtime_samples")
    op.drop_index("ix_client_runtime_samples_client_id_sampled_at", table_name="client_runtime_samples")
    op.drop_table("client_runtime_samples")
    op.drop_column("clients", "traffic_limit_exceeded_at")
    op.drop_column("clients", "traffic_used_30d_tx_bytes")
    op.drop_column("clients", "traffic_used_30d_rx_bytes")
