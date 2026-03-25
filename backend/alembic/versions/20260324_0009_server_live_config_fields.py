"""server live config fields"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0009"
down_revision = "20260323_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("config_source", sa.String(length=50), nullable=False, server_default="generated"))
    op.add_column("servers", sa.Column("live_interface_name", sa.String(length=255), nullable=True))
    op.add_column("servers", sa.Column("live_config_path", sa.String(length=512), nullable=True))
    op.add_column("servers", sa.Column("live_address_cidr", sa.String(length=128), nullable=True))
    op.add_column("servers", sa.Column("live_listen_port", sa.Integer(), nullable=True))
    op.add_column("servers", sa.Column("live_peer_count", sa.Integer(), nullable=True))
    op.add_column("servers", sa.Column("live_runtime_details_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "live_runtime_details_json")
    op.drop_column("servers", "live_peer_count")
    op.drop_column("servers", "live_listen_port")
    op.drop_column("servers", "live_address_cidr")
    op.drop_column("servers", "live_config_path")
    op.drop_column("servers", "live_interface_name")
    op.drop_column("servers", "config_source")
