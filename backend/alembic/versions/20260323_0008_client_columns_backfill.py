"""backfill client columns for legacy local databases"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0008"
down_revision = "20260323_0007"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    client_source = sa.Enum("generated", "imported", name="client_source")
    client_source.create(bind, checkfirst=True)

    if not _column_exists("clients", "private_key_encrypted"):
        op.add_column("clients", sa.Column("private_key_encrypted", sa.Text(), nullable=True))

    if not _column_exists("clients", "source"):
        op.add_column(
            "clients",
            sa.Column("source", client_source, nullable=False, server_default="generated"),
        )

    if not _column_exists("clients", "server_id"):
        op.add_column(
            "clients",
            sa.Column("server_id", sa.Integer(), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True),
        )

    if not _column_exists("clients", "import_note"):
        op.add_column("clients", sa.Column("import_note", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
