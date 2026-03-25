"""client archived flag

Revision ID: 20260325_0017
Revises: 20260325_0016
Create Date: 2026-03-25 14:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0017"
down_revision = "20260325_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("clients", "archived", server_default=None)


def downgrade() -> None:
    op.drop_column("clients", "archived")
