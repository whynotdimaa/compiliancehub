"""Initial: pgvector extension, tenants, users, RLS policies

Revision ID: 0001
Revises:
Create Date: 2026-07-19

Row-Level Security design:
- app connects as a NON-superuser role `app_user` (RLS does not apply to owners
  unless FORCE is used — we use FORCE ROW LEVEL SECURITY to be safe anyway);
- every tenant-scoped table has a policy comparing tenant_id with the
  `app.current_tenant_id` GUC that the application sets via SET LOCAL
  at the start of each transaction.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True, index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=False, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "role",
            sa.Enum("admin", "auditor", "viewer", name="user_role"),
            nullable=False,
            server_default="viewer",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    # --- Row-Level Security -------------------------------------------------
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation_users ON users
        USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )
    # Login flow needs to find a user before tenant context exists.
    # A dedicated permissive policy for the login path: allow SELECT when
    # no tenant is bound (current_setting returns NULL -> policy above fails,
    # this one applies only to the unauthenticated lookup role path).
    op.execute(
        """
        CREATE POLICY login_lookup_users ON users
        FOR SELECT
        USING (current_setting('app.current_tenant_id', true) IS NULL)
        """
    )
    # NB: INSERT of the first admin during registration also happens without
    # tenant context; allow INSERT when no tenant bound (registration path).
    op.execute(
        """
        CREATE POLICY registration_insert_users ON users
        FOR INSERT
        WITH CHECK (current_setting('app.current_tenant_id', true) IS NULL)
        """
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("tenants")
    op.execute("DROP TYPE IF EXISTS user_role")
