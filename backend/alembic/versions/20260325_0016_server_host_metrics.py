"""server host metrics

Revision ID: 20260325_0016
Revises: 20260324_0015
Create Date: 2026-03-25 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0016"
down_revision = "20260324_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("host_metrics_json", sa.Text(), nullable=True))
    op.add_column("servers", sa.Column("host_metrics_refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "server_runtime_samples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("network_rx_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("network_tx_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("network_rx_rate_bps", sa.Float(), nullable=False),
        sa.Column("network_tx_rate_bps", sa.Float(), nullable=False),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False),
        sa.Column("load1", sa.Float(), nullable=False),
        sa.Column("load5", sa.Float(), nullable=False),
        sa.Column("load15", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_server_runtime_samples_server_id", "server_runtime_samples", ["server_id"])
    op.create_index("ix_server_runtime_samples_sampled_at", "server_runtime_samples", ["sampled_at"])


def downgrade() -> None:
    op.drop_index("ix_server_runtime_samples_sampled_at", table_name="server_runtime_samples")
    op.drop_index("ix_server_runtime_samples_server_id", table_name="server_runtime_samples")
    op.drop_table("server_runtime_samples")
    op.drop_column("servers", "host_metrics_refreshed_at")
    op.drop_column("servers", "host_metrics_json")
