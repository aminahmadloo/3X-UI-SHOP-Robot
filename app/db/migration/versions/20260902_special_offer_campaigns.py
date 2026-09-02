"""add named special offer campaigns

Revision ID: 20260902_special_offer_campaigns
Revises: 20260902_special_offers
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_special_offer_campaigns"
down_revision = "20260902_special_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "special_offer_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.UniqueConstraint("title", name="uq_special_offer_campaign_title"),
    )
    op.create_index(
        "ix_special_offer_campaigns_is_default",
        "special_offer_campaigns",
        ["is_default"],
    )
    op.create_index(
        "ix_special_offer_campaigns_is_active",
        "special_offer_campaigns",
        ["is_active"],
    )

    op.create_table(
        "special_offer_campaign_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("special_price_toman", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["special_offer_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["service_purchase_plans.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "plan_id",
            name="uq_special_offer_campaign_plan",
        ),
    )
    op.create_index(
        "ix_special_offer_campaign_plans_campaign_id",
        "special_offer_campaign_plans",
        ["campaign_id"],
    )
    op.create_index(
        "ix_special_offer_campaign_plans_plan_id",
        "special_offer_campaign_plans",
        ["plan_id"],
    )
    op.create_index(
        "ix_special_offer_campaign_plans_is_active",
        "special_offer_campaign_plans",
        ["is_active"],
    )

    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "INSERT INTO special_offer_campaigns "
            "(title, is_default, is_active) VALUES (:title, 1, 1)"
        ),
        {"title": "فروش ویژه عادی"},
    )
    campaign_id = result.lastrowid

    if campaign_id is not None:
        bind.execute(
            sa.text(
                "INSERT INTO special_offer_campaign_plans "
                "(campaign_id, plan_id, special_price_toman, is_active) "
                "SELECT :campaign_id, id, special_offer_price_toman, 1 "
                "FROM service_purchase_plans "
                "WHERE is_custom = 0 "
                "AND is_special_offer = 1 "
                "AND special_offer_price_toman IS NOT NULL "
                "AND special_offer_price_toman > 0"
            ),
            {"campaign_id": campaign_id},
        )


def downgrade() -> None:
    op.drop_index("ix_special_offer_campaign_plans_is_active", table_name="special_offer_campaign_plans")
    op.drop_index("ix_special_offer_campaign_plans_plan_id", table_name="special_offer_campaign_plans")
    op.drop_index("ix_special_offer_campaign_plans_campaign_id", table_name="special_offer_campaign_plans")
    op.drop_table("special_offer_campaign_plans")
    op.drop_index("ix_special_offer_campaigns_is_active", table_name="special_offer_campaigns")
    op.drop_index("ix_special_offer_campaigns_is_default", table_name="special_offer_campaigns")
    op.drop_table("special_offer_campaigns")
