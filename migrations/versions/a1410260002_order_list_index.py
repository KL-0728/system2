"""Support store-scoped order date pagination."""
from alembic import op
revision = 'a1410260002'
down_revision = 'a1410260001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_orders_store_submitted_id', 'orders', ['store_id', 'submitted_at', 'id'])


def downgrade():
    op.drop_index('ix_orders_store_submitted_id', table_name='orders')
