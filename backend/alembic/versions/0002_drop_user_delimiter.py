"""Drop unused users.delimiter column."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_drop_user_delimiter"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "delimiter")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("delimiter", sa.Text(), server_default="::", nullable=False),
    )
