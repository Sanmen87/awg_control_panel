"""add extra service instances

Revision ID: 20260401_0025
Revises: 20260330_0024
Create Date: 2026-04-01 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260401_0025"
down_revision = "20260330_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("service_instances"):
        return
    op.create_table(
        "service_instances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_type", sa.String(length=64), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("runtime_details_json", sa.Text(), nullable=True),
        sa.Column("public_endpoint", sa.String(length=512), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("service_instances")
