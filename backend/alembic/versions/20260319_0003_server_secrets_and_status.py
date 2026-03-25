"""server secrets and status"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0003"
down_revision = "20260319_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("servers", sa.Column("ssh_password_encrypted", sa.Text(), nullable=True))
    op.add_column("servers", sa.Column("ssh_private_key_encrypted", sa.Text(), nullable=True))
    op.add_column("servers", sa.Column("sudo_password_encrypted", sa.Text(), nullable=True))
    op.add_column("servers", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("servers", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "last_error")
    op.drop_column("servers", "last_checked_at")
    op.drop_column("servers", "sudo_password_encrypted")
    op.drop_column("servers", "ssh_private_key_encrypted")
    op.drop_column("servers", "ssh_password_encrypted")
    op.drop_column("servers", "description")
