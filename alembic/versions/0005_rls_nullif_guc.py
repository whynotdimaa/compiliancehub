"""RLS policies: treat empty-string GUC as unset (pooled-connection fix)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19

The gotcha: `set_config('app.current_tenant_id', $1, true)` is transaction-
local, but on a connection where the GUC was never set at session level, the
value after COMMIT becomes '' (empty string) — NOT missing. On a pooled
connection the next transaction then sees current_setting(..., true) = '',
and `''::uuid` raises InvalidTextRepresentation inside the policy itself:
registration 500s, login stops finding users. Every policy must go through
NULLIF(current_setting(...), '') so an empty string means "no tenant bound",
exactly like NULL.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUC = "NULLIF(current_setting('app.current_tenant_id', true), '')"

TENANT_TABLES = ["users", "documents", "document_chunks", "evaluation_records"]


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation_{table} ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id = {GUC}::uuid)
            WITH CHECK (tenant_id = {GUC}::uuid)
            """
        )

    op.execute("DROP POLICY login_lookup_users ON users")
    op.execute(
        f"""
        CREATE POLICY login_lookup_users ON users
        FOR SELECT USING ({GUC} IS NULL)
        """
    )
    op.execute("DROP POLICY registration_insert_users ON users")
    op.execute(
        f"""
        CREATE POLICY registration_insert_users ON users
        FOR INSERT WITH CHECK ({GUC} IS NULL)
        """
    )


def downgrade() -> None:
    raw = "current_setting('app.current_tenant_id', true)"
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation_{table} ON {table}")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id = {raw}::uuid)
            WITH CHECK (tenant_id = {raw}::uuid)
            """
        )
    op.execute("DROP POLICY login_lookup_users ON users")
    op.execute(f"CREATE POLICY login_lookup_users ON users FOR SELECT USING ({raw} IS NULL)")
    op.execute("DROP POLICY registration_insert_users ON users")
    op.execute(
        f"CREATE POLICY registration_insert_users ON users FOR INSERT WITH CHECK ({raw} IS NULL)"
    )
