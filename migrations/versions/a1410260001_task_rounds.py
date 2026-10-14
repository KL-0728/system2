"""Keep every operational exception round without rewriting history."""
from alembic import op
import sqlalchemy as sa
revision = 'a1410260001'
down_revision = '884e7a53a8c8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('operational_tasks', sa.Column('round', sa.Integer(), nullable=False, server_default='1'))
    # MySQL needs the store FK index even while replacing its unique index.
    op.drop_constraint('uq_operational_tasks_store_id', 'operational_tasks', type_='unique')
    op.create_unique_constraint('uq_operational_tasks_store_id', 'operational_tasks',
        ['store_id', 'source_type', 'source_id', 'task_type', 'round'])


def downgrade():
    raise RuntimeError('異常輪次保留歷史；請使用驗證過的備份還原，不做破壞性降版')
