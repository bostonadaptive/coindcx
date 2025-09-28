"""Add paper_order_id to paper_trades and backfill existing rows

Revision ID: 20251001_add_paper_order_id
Revises: 20250925_add_currency_and_is_paper
Create Date: 2025-10-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import uuid

# revision identifiers, used by Alembic.
revision = '20251001_add_paper_order_id'
down_revision = '20250925_add_currency_and_is_paper'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else None

    # Add the column (best-effort: if it already exists this will be ignored)
    try:
        op.add_column('paper_trades', sa.Column('paper_order_id', sa.String(length=80), nullable=True))
    except Exception:
        # If the column already exists or the table is missing, continue silently
        pass

    # Backfill existing rows with generated PAPER-<uuid> identifiers where missing
    try:
        conn = op.get_bind()
        # Select rows missing paper_order_id
        select_sql = sa.text("SELECT id FROM paper_trades WHERE paper_order_id IS NULL OR paper_order_id = ''")
        result = conn.execute(select_sql)
        ids = [row[0] for row in result]
        for _id in ids:
            new_val = 'PAPER-' + uuid.uuid4().hex
            conn.execute(sa.text("UPDATE paper_trades SET paper_order_id = :val WHERE id = :id"), {'val': new_val, 'id': _id})
    except Exception:
        # best-effort backfill; ignore failures
        pass


def downgrade():
    # Remove the column (best-effort)
    try:
        op.drop_column('paper_trades', 'paper_order_id')
    except Exception:
        pass
