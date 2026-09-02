"""Hide invalid zero-day service periods from management and offers."""

from alembic import op


revision = "20260902_cleanup_invalid_zero_day_periods"
down_revision = "20260902_cleanup_invalid_special_offer_command"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Invalid legacy periods must not appear as manageable/active periods.
    op.execute(
        """
        UPDATE service_periods
        SET is_active = 0,
            is_archived = 1
        WHERE months <= 0 OR duration_days <= 0
        """
    )

    # Also remove any campaign assignment pointing at an invalid zero-day plan.
    op.execute(
        """
        DELETE FROM special_offer_campaign_plans
        WHERE plan_id IN (
            SELECT id
            FROM service_purchase_plans
            WHERE duration_days <= 0
        )
        """
    )


def downgrade() -> None:
    # This cleanup is intentionally irreversible because the original invalid
    # period state is not meaningful and its campaign assignments may have
    # represented stale data.
    pass
