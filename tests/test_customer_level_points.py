from app.bot.services.customer_level import CustomerLevel, LEVELS, level_for_points


def test_customer_level_uses_total_points_thresholds() -> None:
    assert level_for_points(0, LEVELS).title == "سطح پایه"
    assert level_for_points(4, LEVELS).title == "سطح پایه"
    assert level_for_points(5, LEVELS).title == "سطح برنزی"
    assert level_for_points(10, LEVELS).title == "سطح برنزی"
    assert level_for_points(11, LEVELS).title == "سطح نقره‌ای"
    assert level_for_points(20, LEVELS).title == "سطح نقره‌ای"
    assert level_for_points(21, LEVELS).title == "سطح طلایی"
    assert level_for_points(100, LEVELS).title == "سطح طلایی"


def test_customer_level_discounts_keep_existing_defaults() -> None:
    assert [level.discount_percent for level in LEVELS] == [0, 10, 15, 20]


def test_customer_level_uses_configured_point_ranges() -> None:
    levels = (
        CustomerLevel("base", "سطح پایه", 0, 2, 0),
        CustomerLevel("bronze", "سطح برنزی", 3, 7, 12),
        CustomerLevel("silver", "سطح نقره‌ای", 8, 14, 18),
        CustomerLevel("gold", "سطح طلایی", 15, None, 25),
    )

    assert level_for_points(2, levels).title == "سطح پایه"
    assert level_for_points(3, levels).title == "سطح برنزی"
    assert level_for_points(7, levels).title == "سطح برنزی"
    assert level_for_points(8, levels).title == "سطح نقره‌ای"
    assert level_for_points(14, levels).title == "سطح نقره‌ای"
    assert level_for_points(15, levels).title == "سطح طلایی"
    assert level_for_points(100, levels).title == "سطح طلایی"
