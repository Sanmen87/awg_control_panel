"""normalize service instance enum columns to varchar

Revision ID: 20260401_0027
Revises: 20260401_0026
Create Date: 2026-04-01 17:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260401_0027"
down_revision = "20260401_0026"
branch_labels = None
depends_on = None


def _column_udt_name(inspector: sa.Inspector, column_name: str) -> str | None:
    for column in inspector.get_columns("service_instances"):
        if column["name"] == column_name:
            column_type = column["type"]
            return getattr(column_type, "name", None)
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("service_instances"):
        return

    service_type_udt = _column_udt_name(inspector, "service_type")
    status_udt = _column_udt_name(inspector, "status")

    if service_type_udt == "service_type":
        op.execute(
            """
            ALTER TABLE service_instances
            ALTER COLUMN service_type TYPE VARCHAR(64)
            USING service_type::text
            """
        )

    if status_udt == "service_status":
        op.execute(
            """
            ALTER TABLE service_instances
            ALTER COLUMN status TYPE VARCHAR(64)
            USING status::text
            """
        )

    op.execute("DROP TYPE IF EXISTS service_status")
    op.execute("DROP TYPE IF EXISTS service_type")


def downgrade() -> None:
    pass
