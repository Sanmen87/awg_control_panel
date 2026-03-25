"""client runtime stats

Revision ID: 20260324_0011
Revises: 20260324_0010
Create Date: 2026-03-24 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0011"
down_revision = "20260324_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("runtime_connected", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("clients", sa.Column("latest_handshake_human", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("data_received_human", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("data_sent_human", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("runtime_refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("clients", "runtime_connected", server_default=None)


def downgrade() -> None:
    op.drop_column("clients", "runtime_refreshed_at")
    op.drop_column("clients", "data_sent_human")
    op.drop_column("clients", "data_received_human")
    op.drop_column("clients", "latest_handshake_human")
    op.drop_column("clients", "runtime_connected")
