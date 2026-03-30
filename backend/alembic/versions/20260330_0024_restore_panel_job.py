"""add restore-panel job type

Revision ID: 20260330_0024
Revises: 20260330_0023
Create Date: 2026-03-30 13:40:00.000000
"""

from alembic import op


revision = "20260330_0024"
down_revision = "20260330_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'restore-panel'")


def downgrade() -> None:
    pass
