"""client manual disabled flag

Revision ID: 20260324_0014
Revises: 20260324_0013
Create Date: 2026-03-24 18:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0014"
down_revision = "20260324_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("manual_disabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("clients", "manual_disabled", server_default=None)


def downgrade() -> None:
    op.drop_column("clients", "manual_disabled")
