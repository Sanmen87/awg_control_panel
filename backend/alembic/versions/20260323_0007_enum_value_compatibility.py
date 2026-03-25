"""normalize legacy enum labels to current value format"""

from alembic import op


revision = "20260323_0007"
down_revision = "20260323_0006"
branch_labels = None
depends_on = None


def _rename_enum_value(enum_name: str, old_value: str, new_value: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE t.typname = '{enum_name}' AND e.enumlabel = '{old_value}'
            ) THEN
                ALTER TYPE {enum_name} RENAME VALUE '{old_value}' TO '{new_value}';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # Earlier local create_all-based schemas used enum member names such as
    # STANDARD_VPN / PROXY_EXIT / PENDING. Current migrations and API use the
    # actual string values such as standard-vpn / proxy-exit / pending.
    with op.get_context().autocommit_block():
        _rename_enum_value("server_role", "STANDARD_VPN", "standard-vpn")
        _rename_enum_value("server_role", "PROXY", "proxy")
        _rename_enum_value("server_role", "EXIT", "exit")
        _rename_enum_value("server_role", "PROXY_SECONDARY", "proxy-secondary")

        _rename_enum_value("server_status", "NEW", "new")
        _rename_enum_value("server_status", "HEALTHY", "healthy")
        _rename_enum_value("server_status", "DEGRADED", "degraded")
        _rename_enum_value("server_status", "ERROR", "error")

        _rename_enum_value("topology_type", "STANDARD", "standard")
        _rename_enum_value("topology_type", "PROXY_EXIT", "proxy-exit")
        _rename_enum_value("topology_type", "PROXY_MULTI_EXIT", "proxy-multi-exit")

        _rename_enum_value("topology_status", "DRAFT", "draft")
        _rename_enum_value("topology_status", "PENDING", "pending")
        _rename_enum_value("topology_status", "APPLIED", "applied")
        _rename_enum_value("topology_status", "ERROR", "error")

        _rename_enum_value("topology_node_role", "STANDARD_VPN", "standard-vpn")
        _rename_enum_value("topology_node_role", "PROXY", "proxy")
        _rename_enum_value("topology_node_role", "EXIT", "exit")
        _rename_enum_value("topology_node_role", "PROXY_SECONDARY", "proxy-secondary")

        _rename_enum_value("job_type", "BOOTSTRAP_SERVER", "bootstrap-server")
        _rename_enum_value("job_type", "DEPLOY_TOPOLOGY", "deploy-topology")
        _rename_enum_value("job_type", "CHECK_SERVER", "check-server")
        _rename_enum_value("job_type", "DETECT_AWG", "detect-awg")
        _rename_enum_value("job_type", "BACKUP", "backup")

        _rename_enum_value("job_status", "PENDING", "pending")
        _rename_enum_value("job_status", "RUNNING", "running")
        _rename_enum_value("job_status", "SUCCEEDED", "succeeded")
        _rename_enum_value("job_status", "FAILED", "failed")

        _rename_enum_value("backup_type", "DATABASE", "database")
        _rename_enum_value("backup_type", "CONFIGS", "configs")
        _rename_enum_value("backup_type", "FULL", "full")

        _rename_enum_value("backup_status", "PENDING", "pending")
        _rename_enum_value("backup_status", "RUNNING", "running")
        _rename_enum_value("backup_status", "SUCCEEDED", "succeeded")
        _rename_enum_value("backup_status", "FAILED", "failed")

        _rename_enum_value("install_method", "NATIVE", "native")
        _rename_enum_value("install_method", "DOCKER", "docker")
        _rename_enum_value("install_method", "CUSTOM", "custom")
        _rename_enum_value("install_method", "UNKNOWN", "unknown")

        _rename_enum_value("access_status", "PENDING", "pending")
        _rename_enum_value("access_status", "OK", "ok")
        _rename_enum_value("access_status", "FAILED", "failed")

        _rename_enum_value("awg_status", "UNKNOWN", "unknown")
        _rename_enum_value("awg_status", "DETECTED", "detected")
        _rename_enum_value("awg_status", "MISSING", "missing")

        _rename_enum_value("client_source", "GENERATED", "generated")
        _rename_enum_value("client_source", "IMPORTED", "imported")


def downgrade() -> None:
    pass
