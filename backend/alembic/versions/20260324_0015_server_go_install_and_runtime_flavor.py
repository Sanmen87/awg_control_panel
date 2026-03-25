"""server go install and runtime flavor

Revision ID: 20260324_0015
Revises: 20260324_0014
Create Date: 2026-03-24 19:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0015"
down_revision = "20260324_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE install_method ADD VALUE IF NOT EXISTS 'go'")
    op.add_column("servers", sa.Column("runtime_flavor", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "runtime_flavor")
