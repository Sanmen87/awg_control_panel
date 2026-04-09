"""server onboarding states"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260323_0006"
down_revision = "20260323_0005"
branch_labels = None
depends_on = None


access_status = postgresql.ENUM("pending", "ok", "failed", name="access_status", create_type=False)
awg_status = postgresql.ENUM("unknown", "detected", "missing", name="awg_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    access_status.create(bind, checkfirst=True)
    awg_status.create(bind, checkfirst=True)
    # PostgreSQL requires new enum values added via ALTER TYPE to be committed
    # before they can be safely referenced by later statements.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE install_method ADD VALUE IF NOT EXISTS 'unknown'")

    op.add_column("servers", sa.Column("os_name", sa.String(length=255), nullable=True))
    op.add_column("servers", sa.Column("os_version", sa.String(length=255), nullable=True))
    op.add_column("servers", sa.Column("access_status", access_status, nullable=False, server_default="pending"))
    op.add_column("servers", sa.Column("awg_status", awg_status, nullable=False, server_default="unknown"))
    op.add_column("servers", sa.Column("ready_for_topology", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("servers", "ready_for_topology")
    op.drop_column("servers", "awg_status")
    op.drop_column("servers", "access_status")
    op.drop_column("servers", "os_version")
    op.drop_column("servers", "os_name")

    bind = op.get_bind()
    awg_status.drop(bind, checkfirst=True)
    access_status.drop(bind, checkfirst=True)
