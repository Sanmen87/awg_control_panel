"""add install-extra-service job type

Revision ID: 20260401_0026
Revises: 20260401_0025
Create Date: 2026-04-01 17:10:00.000000
"""

from alembic import op


revision = "20260401_0026"
down_revision = "20260401_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'install-extra-service'")


def downgrade() -> None:
    pass
