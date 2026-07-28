"""Drop unused users.delimiter column."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_drop_user_delimiter"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "delimiter")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("delimiter", sa.Text(), server_default="::", nullable=False),
    )
