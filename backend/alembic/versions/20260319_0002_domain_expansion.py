"""domain expansion"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0002"
down_revision = "20260319_0001"
branch_labels = None
depends_on = None


topology_node_role = sa.Enum("standard-vpn", "proxy", "exit", "proxy-secondary", name="topology_node_role", create_type=False)
job_type = sa.Enum("bootstrap-server", "deploy-topology", "check-server", "backup", name="job_type", create_type=False)
job_status = sa.Enum("pending", "running", "succeeded", "failed", name="job_status", create_type=False)
backup_type = sa.Enum("database", "configs", "full", name="backup_type", create_type=False)
backup_status = sa.Enum("pending", "running", "succeeded", "failed", name="backup_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    topology_node_role.create(bind, checkfirst=True)
    job_type.create(bind, checkfirst=True)
    job_status.create(bind, checkfirst=True)
    backup_type.create(bind, checkfirst=True)
    backup_status.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "topology_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topology_id", sa.Integer(), sa.ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("server_id", sa.Integer(), sa.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", topology_node_role, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("topology_id", "server_id", name="uq_topology_server"),
    )

    op.create_table(
        "deployment_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("server_id", sa.Integer(), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("topology_id", sa.Integer(), sa.ForeignKey("topologies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "backup_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backup_type", backup_type, nullable=False),
        sa.Column("status", backup_status, nullable=False, server_default="pending"),
        sa.Column("storage_path", sa.String(length=512), nullable=True),
        sa.Column("result_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "failover_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topology_id", sa.Integer(), sa.ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_exit_server_id", sa.Integer(), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("new_exit_server_id", sa.Integer(), sa.ForeignKey("servers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("trigger_source", sa.String(length=50), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("failover_events")
    op.drop_table("backup_jobs")
    op.drop_table("deployment_jobs")
    op.drop_table("topology_nodes")
    op.drop_table("users")

    bind = op.get_bind()
    backup_status.drop(bind, checkfirst=True)
    backup_type.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)
    job_type.drop(bind, checkfirst=True)
    topology_node_role.drop(bind, checkfirst=True)
