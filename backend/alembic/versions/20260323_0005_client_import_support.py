"""client import support"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0005"
down_revision = "20260319_0004"
branch_labels = None
depends_on = None


client_source = sa.Enum("generated", "imported", name="client_source", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    client_source.create(bind, checkfirst=True)

    op.add_column("clients", sa.Column("private_key_encrypted", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("source", client_source, nullable=False, server_default="generated"))
    op.add_column("clients", sa.Column("server_id", sa.Integer(), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True))
    op.add_column("clients", sa.Column("import_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "import_note")
    op.drop_column("clients", "server_id")
    op.drop_column("clients", "source")
    op.drop_column("clients", "private_key_encrypted")

    bind = op.get_bind()
    client_source.drop(bind, checkfirst=True)
