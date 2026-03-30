"""add default exit fields for proxy multi-exit

Revision ID: 20260329_0021
Revises: 20260326_0020
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260329_0021"
down_revision = "20260326_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "topologies",
        sa.Column("default_exit_server_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_topologies_default_exit_server_id_servers",
        "topologies",
        "servers",
        ["default_exit_server_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "clients",
        sa.Column("exit_server_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_clients_exit_server_id_servers",
        "clients",
        "servers",
        ["exit_server_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_clients_exit_server_id_servers", "clients", type_="foreignkey")
    op.drop_column("clients", "exit_server_id")

    op.drop_constraint("fk_topologies_default_exit_server_id_servers", "topologies", type_="foreignkey")
    op.drop_column("topologies", "default_exit_server_id")
