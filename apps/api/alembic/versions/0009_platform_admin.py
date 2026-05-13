"""Platform admin role + user-invite flow.

Adds `is_platform_admin` to users so a single super-admin can manage
organizations + users across the whole system (founder use case).
Also stores when each user was last invited so the management dashboard
can show pending invites distinctly from accepted ones.

Revision ID: 0009_platform_admin
Revises: 0008_wespennest
Create Date: 2026-05-13
"""

from typing import Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_platform_admin"
down_revision: Union[str, None] = "0008_wespennest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-user platform admin flag.  These users can see ALL orgs and
    # users, can create orgs, can invite users into any org.
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Pending-invite tracking. When a user is invited but hasn't logged in
    # yet, we set invited_at + invited_by but leave password_hash NULL.
    op.add_column(
        "users",
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("invite_token", sa.String(120), nullable=True),
    )
    op.create_index(
        "ix_users_invite_token",
        "users",
        ["invite_token"],
        postgresql_where=sa.text("invite_token IS NOT NULL"),
    )

    # Promote our founder account to platform admin.
    op.execute(
        """
        UPDATE users SET is_platform_admin = true
        WHERE email = 'founder@hostingportal.org';
        """
    )


def downgrade() -> None:
    op.drop_index("ix_users_invite_token", table_name="users")
    op.drop_column("users", "invite_token")
    op.drop_column("users", "invited_by")
    op.drop_column("users", "invited_at")
    op.drop_column("users", "is_platform_admin")
