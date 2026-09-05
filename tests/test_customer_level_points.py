from app.bot.services.customer_level import LEVELS, level_for_points


def test_customer_level_uses_total_points_thresholds() -> None:
    assert level_for_points(0, LEVELS).title == "میخ آهنی"
    assert level_for_points(4, LEVELS).title == "میخ آهنی"
    assert level_for_points(5, LEVELS).title == "میخ فولادی"
    assert level_for_points(10, LEVELS).title == "میخ فولادی"
    assert level_for_points(11, LEVELS).title == "میخ تیتانیومی"
    assert level_for_points(20, LEVELS).title == "میخ تیتانیومی"
    assert level_for_points(21, LEVELS).title == "میخ طلایی"
    assert level_for_points(100, LEVELS).title == "میخ طلایی"


def test_customer_level_discounts_keep_existing_defaults() -> None:
    assert [level.discount_percent for level in LEVELS] == [0, 10, 15, 20]
