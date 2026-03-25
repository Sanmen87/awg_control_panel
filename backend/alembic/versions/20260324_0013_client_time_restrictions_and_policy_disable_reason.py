"""client time restrictions and policy disable reason

Revision ID: 20260324_0013
Revises: 20260324_0012
Create Date: 2026-03-24 18:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0013"
down_revision = "20260324_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("quiet_hours_start_minute", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("quiet_hours_end_minute", sa.Integer(), nullable=True))
    op.add_column("clients", sa.Column("quiet_hours_timezone", sa.String(length=64), nullable=True))
    op.add_column("clients", sa.Column("policy_disabled_reason", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "policy_disabled_reason")
    op.drop_column("clients", "quiet_hours_timezone")
    op.drop_column("clients", "quiet_hours_end_minute")
    op.drop_column("clients", "quiet_hours_start_minute")
