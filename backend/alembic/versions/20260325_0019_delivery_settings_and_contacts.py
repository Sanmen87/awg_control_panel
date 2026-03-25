"""delivery settings and contacts

Revision ID: 20260325_0019
Revises: 20260325_0018
Create Date: 2026-03-25 17:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0019"
down_revision = "20260325_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("delivery_email", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("delivery_telegram_chat_id", sa.String(length=128), nullable=True))
    op.add_column("clients", sa.Column("delivery_telegram_username", sa.String(length=255), nullable=True))
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_settings_key", "app_settings", ["key"], unique=True)
    op.create_table(
        "delivery_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("payload_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_logs_client_id", "delivery_logs", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_logs_client_id", table_name="delivery_logs")
    op.drop_table("delivery_logs")
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.drop_table("app_settings")
    op.drop_column("clients", "delivery_telegram_username")
    op.drop_column("clients", "delivery_telegram_chat_id")
    op.drop_column("clients", "delivery_email")
