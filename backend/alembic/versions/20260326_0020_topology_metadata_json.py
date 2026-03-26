"""add topology metadata json

Revision ID: 20260326_0020
Revises: 20260325_0019
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260326_0020"
down_revision = "20260325_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("topologies", sa.Column("metadata_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("topologies", "metadata_json")
