from alembic import op
import sqlalchemy as sa


revision = "20260821_seed_default_service_periods"
down_revision = "20260821_dynamic_service_periods"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    table = sa.table(
        "service_periods",
        sa.column("name", sa.String),
        sa.column("months", sa.Integer),
        sa.column("duration_days", sa.Integer),
        sa.column("service_type", sa.String),
        sa.column("traffic_addon_service_type", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_archived", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )

    existing = conn.execute(
        sa.text("SELECT months FROM service_periods")
    ).fetchall()

    months = {x[0] for x in existing}

    rows = []

    if 1 not in months:
        rows.append({
            "name": "سرویس‌های 1 ماهه",
            "months": 1,
            "duration_days": 30,
            "service_type": "one_month",
            "traffic_addon_service_type": "traffic_addon_30",
            "is_active": True,
            "is_archived": False,
            "sort_order": 1,
        })

    if 3 not in months:
        rows.append({
            "name": "سرویس‌های 3 ماهه",
            "months": 3,
            "duration_days": 90,
            "service_type": "three_month",
            "traffic_addon_service_type": "traffic_addon_90",
            "is_active": True,
            "is_archived": False,
            "sort_order": 3,
        })

    if rows:
        op.bulk_insert(table, rows)


def downgrade():
    op.execute(
        "DELETE FROM service_periods WHERE months IN (1,3)"
    )
