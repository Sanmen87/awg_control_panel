"""add client service_peer flag

Revision ID: 20260414_0029
Revises: 20260407_0028
Create Date: 2026-04-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260414_0029"
down_revision = "20260407_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("service_peer", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE clients SET service_peer = FALSE WHERE service_peer IS NULL")
    op.alter_column("clients", "service_peer", server_default=None)


def downgrade() -> None:
    op.drop_column("clients", "service_peer")
