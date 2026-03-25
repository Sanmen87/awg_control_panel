"""install method and awg detection"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0004"
down_revision = "20260319_0003"
branch_labels = None
depends_on = None


install_method = sa.Enum("native", "docker", "custom", name="install_method")


def upgrade() -> None:
    bind = op.get_bind()
    install_method.create(bind, checkfirst=True)
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'detect-awg'")

    op.add_column("servers", sa.Column("install_method", install_method, nullable=False, server_default="native"))
    op.add_column("servers", sa.Column("awg_detected", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("servers", sa.Column("awg_version", sa.String(length=255), nullable=True))
    op.add_column("servers", sa.Column("awg_interfaces_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "awg_interfaces_json")
    op.drop_column("servers", "awg_version")
    op.drop_column("servers", "awg_detected")
    op.drop_column("servers", "install_method")

    bind = op.get_bind()
    install_method.drop(bind, checkfirst=True)
