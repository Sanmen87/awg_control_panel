"""client materials and preshared key

Revision ID: 20260324_0010
Revises: 20260324_0009
Create Date: 2026-03-24 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0010"
down_revision = "20260324_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("preshared_key_encrypted", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("config_ubuntu_encrypted", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("config_amneziawg_encrypted", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("config_amneziavpn_encrypted", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("qr_png_base64_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "qr_png_base64_encrypted")
    op.drop_column("clients", "config_amneziavpn_encrypted")
    op.drop_column("clients", "config_amneziawg_encrypted")
    op.drop_column("clients", "config_ubuntu_encrypted")
    op.drop_column("clients", "preshared_key_encrypted")
