"""Add currency to users/credentials and is_paper to user_strategy_setup

Revision ID: 20250925_add_currency_and_is_paper
Revises: None (initial)
Create Date: 2025-09-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250925_add_currency_and_is_paper'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else None

    # Add currency column to users with default 'INR'
    if dialect == 'sqlite':
        # SQLite: add column with nullable and then populate default
        op.add_column('users', sa.Column('currency', sa.String(length=10), nullable=True))
        op.execute("UPDATE users SET currency='INR' WHERE currency IS NULL")
    else:
        op.add_column('users', sa.Column('currency', sa.String(length=10), nullable=True, server_default=sa.text("'INR'")))

    # Add currency column to credentials
    op.add_column('credentials', sa.Column('currency', sa.String(length=10), nullable=True))

    # Add is_paper column to user_strategy_setup
    if dialect == 'sqlite':
        op.add_column('user_strategy_setup', sa.Column('is_paper', sa.Integer(), nullable=True))
        op.execute("UPDATE user_strategy_setup SET is_paper=0 WHERE is_paper IS NULL")
    else:
        op.add_column('user_strategy_setup', sa.Column('is_paper', sa.Boolean(), nullable=True, server_default=sa.text('0')))


def downgrade():
    # Remove columns (best-effort)
    try:
        op.drop_column('user_strategy_setup', 'is_paper')
    except Exception:
        pass
    try:
        op.drop_column('credentials', 'currency')
    except Exception:
        pass
    try:
        op.drop_column('users', 'currency')
    except Exception:
        pass
