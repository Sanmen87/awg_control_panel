"""external api tokens and audit actors

Revision ID: 20260415_0030
Revises: 20260414_0029
Create Date: 2026-04-15 13:55:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260415_0030"
down_revision: Union[str, None] = "20260414_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_prefix", sa.String(length=32), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_api_tokens_token_prefix", "api_tokens", ["token_prefix"])

    op.add_column(
        "audit_logs",
        sa.Column("actor_type", sa.String(length=50), nullable=False, server_default="admin_user"),
    )
    op.add_column("audit_logs", sa.Column("actor_id", sa.String(length=100), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_name", sa.String(length=255), nullable=True))
    op.add_column("audit_logs", sa.Column("metadata_json", sa.Text(), nullable=True))
    op.execute("UPDATE audit_logs SET actor_id = user_id::text WHERE user_id IS NOT NULL AND actor_id IS NULL")
    op.alter_column("audit_logs", "actor_type", server_default=None)
    op.alter_column("api_tokens", "scopes_json", server_default=None)
    op.alter_column("api_tokens", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_column("audit_logs", "metadata_json")
    op.drop_column("audit_logs", "actor_name")
    op.drop_column("audit_logs", "actor_id")
    op.drop_column("audit_logs", "actor_type")
    op.drop_index("ix_api_tokens_token_prefix", table_name="api_tokens")
    op.drop_table("api_tokens")
