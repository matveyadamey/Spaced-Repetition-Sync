"""Add decks table and cards.deck_id."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_decks"
down_revision: Union[str, None] = "0002_drop_user_delimiter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name_normalized", name="uq_decks_user_name"),
    )
    op.create_index("ix_decks_user_id", "decks", ["user_id"])

    op.add_column("cards", sa.Column("deck_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_cards_deck_id",
        "cards",
        "decks",
        ["deck_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_cards_deck_id", "cards", ["deck_id"])
    op.create_index("ix_cards_source_file", "cards", ["user_id", "source_file"])


def downgrade() -> None:
    op.drop_index("ix_cards_source_file", table_name="cards")
    op.drop_index("ix_cards_deck_id", table_name="cards")
    op.drop_constraint("fk_cards_deck_id", "cards", type_="foreignkey")
    op.drop_column("cards", "deck_id")
    op.drop_index("ix_decks_user_id", table_name="decks")
    op.drop_table("decks")
