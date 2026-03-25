"""bigint traffic and server metrics

Revision ID: 20260325_0018
Revises: 20260325_0017
Create Date: 2026-03-25 16:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0018"
down_revision = "20260325_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("clients", "traffic_used_30d_rx_bytes", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("clients", "traffic_used_30d_tx_bytes", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "memory_used_bytes", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "memory_total_bytes", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "disk_used_bytes", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "disk_total_bytes", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "network_rx_bytes_total", type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "network_tx_bytes_total", type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("server_runtime_samples", "network_tx_bytes_total", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "network_rx_bytes_total", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "disk_total_bytes", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "disk_used_bytes", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "memory_total_bytes", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("server_runtime_samples", "memory_used_bytes", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("clients", "traffic_used_30d_tx_bytes", type_=sa.Integer(), existing_nullable=False)
    op.alter_column("clients", "traffic_used_30d_rx_bytes", type_=sa.Integer(), existing_nullable=False)
