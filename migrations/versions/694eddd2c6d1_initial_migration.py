"""initial migration

Revision ID: 694eddd2c6d1
Revises: 
Create Date: 2024-04-19 18:05:15.123456

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '694eddd2c6d1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create Question table
    op.create_table('question',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_text', sa.String(length=500), nullable=False),
        sa.Column('options', sa.String(length=500), nullable=False),
        sa.Column('correct_answer', sa.Integer(), nullable=False),
        sa.Column('explanation', sa.String(length=500), nullable=False),
        sa.Column('times_used', sa.Integer(), nullable=True),
        sa.Column('last_used', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create Test table
    op.create_table('test',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('total_questions', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('questions_used', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('test')
    op.drop_table('question')
