"""add restore-server job type

Revision ID: 20260330_0023
Revises: 20260330_0022
Create Date: 2026-03-30
"""

from alembic import op


revision = "20260330_0023"
down_revision = "20260330_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'restore-server'")


def downgrade() -> None:
    pass
