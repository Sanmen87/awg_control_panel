"""add server backup support

Revision ID: 20260330_0022
Revises: 20260329_0021
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa


revision = "20260330_0022"
down_revision = "20260329_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE backup_type ADD VALUE IF NOT EXISTS 'server'")
    op.add_column("backup_jobs", sa.Column("server_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_backup_jobs_server_id_servers",
        "backup_jobs",
        "servers",
        ["server_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_backup_jobs_server_id_servers", "backup_jobs", type_="foreignkey")
    op.drop_column("backup_jobs", "server_id")
