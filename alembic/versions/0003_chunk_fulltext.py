"""Full-text search on chunks: generated tsvector column + GIN index

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19

A STORED generated column keeps the tsvector in sync with `text` at write time —
no triggers, no application code to forget. The column is intentionally NOT
mapped in the ORM model: it is Postgres-only, and mapping it would break the
SQLite unit-test metadata. FTS queries use textual SQL in app/retrieval.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN text_search tsvector
        GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_text_search
        ON document_chunks USING gin (text_search)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_document_chunks_text_search")
    op.execute("ALTER TABLE document_chunks DROP COLUMN text_search")
