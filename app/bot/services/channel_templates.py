"""Template definitions, validation, and rendering for Telegram channel posts."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.db.models import ChannelContent, ChannelContentTemplate

_VARIABLE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def variable(key: str, label: str, description: str, example: str, *, required: bool = True) -> dict[str, Any]:
    """Build the persisted documentation for one template variable."""
    return {"key": key, "label": label, "description": description, "example": example, "required": required}


TEMPLATE_DEFINITIONS = {
    "special_offer": {
        "title": "🔥 فروش ویژه",
        "purpose": "برای معرفی تخفیف و پیشنهاد فروش",
        "body": "🔥 <b>{service_name}</b>\n\n📦 حجم: {volume}\n⏳ مدت: {duration}\n💰 قیمت ویژه: <b>{price}</b>\n🎁 تخفیف: {discount}\n\n{buy_link}",
        "variables": [
            variable("service_name", "نام سرویس", "نام سرویس VPN که ارائه می‌شود.", "سرویس طلایی"),
            variable("volume", "حجم", "حجم ترافیک سرویس.", "100 گیگ"),
            variable("duration", "مدت", "مدت اعتبار سرویس.", "30 روز"),
            variable("price", "قیمت", "قیمت نهایی پیشنهاد.", "100 هزار تومان"),
            variable("old_price", "قیمت قبل", "قیمت پیش از تخفیف.", "150 هزار تومان", required=False),
            variable("discount", "درصد تخفیف", "میزان تخفیف یا متن تخفیف.", "30٪"),
            variable("buy_link", "لینک خرید", "لینک مستقیم خرید سرویس.", "https://example.com/buy"),
            variable("support_link", "لینک پشتیبانی", "لینک تماس با پشتیبانی.", "https://t.me/support", required=False),
        ],
    },
    "server_notice": {
        "title": "⚡ اطلاعیه سرور",
        "purpose": "برای اطلاع‌رسانی وضعیت یا تغییرات سرور",
        "body": "⚡ <b>اطلاعیه سرور</b>\n\n{service_name}\n\nپشتیبانی: {support_link}",
        "variables": [
            variable("service_name", "عنوان اطلاعیه", "خلاصه وضعیت یا موضوع اطلاعیه.", "به‌روزرسانی سرور آلمان"),
            variable("support_link", "لینک پشتیبانی", "لینک تماس با پشتیبانی.", "https://t.me/support"),
        ],
    },
    "maintenance": {
        "title": "🛠 قطعی و تعمیرات",
        "purpose": "برای اعلام تعمیرات برنامه‌ریزی‌شده",
        "body": "🛠 <b>تعمیرات برنامه‌ریزی‌شده</b>\n\n{service_name}\n⏳ مدت تقریبی: {duration}\n\nپشتیبانی: {support_link}",
        "variables": [
            variable("service_name", "سرویس یا سرور", "سرویسی که تعمیرات آن انجام می‌شود.", "سرور آلمان"),
            variable("duration", "مدت تقریبی", "زمان تقریبی تعمیرات.", "30 دقیقه"),
            variable("support_link", "لینک پشتیبانی", "لینک تماس با پشتیبانی.", "https://t.me/support"),
        ],
    },
    "referral": {
        "title": "🎯 معرفی دوستان",
        "purpose": "برای دعوت کاربران به معرفی دوستان",
        "body": "🎯 <b>دوستانت را دعوت کن</b>\n\n{discount}\n\n{buy_link}",
        "variables": [
            variable("discount", "متن جایزه", "توضیح جایزه یا تخفیف معرفی دوستان.", "20٪ تخفیف برای هر دعوت"),
            variable("buy_link", "لینک دعوت", "لینک معرفی یا خرید.", "https://example.com/invite"),
        ],
    },
    "renewal": {
        "title": "🔄 تمدید سرویس",
        "purpose": "برای یادآوری تمدید سرویس کاربران",
        "body": "🔄 <b>وقت تمدید سرویس است</b>\n\n{service_name}\n📦 {volume} / {duration}\n💰 {price}\n\n{buy_link}",
        "variables": [
            variable("service_name", "نام سرویس", "نام سرویس قابل تمدید.", "VIP 100GB"),
            variable("volume", "حجم", "حجم سرویس.", "100 گیگ"),
            variable("duration", "مدت", "مدت اعتبار پس از تمدید.", "30 روز"),
            variable("price", "قیمت", "هزینه تمدید.", "100 هزار تومان"),
            variable("buy_link", "لینک تمدید", "لینک مستقیم تمدید سرویس.", "https://example.com/renew"),
        ],
    },
    "custom": {
        "title": "✏️ سفارشی",
        "purpose": "برای نوشتن یک پیام کوتاه و آزاد",
        "body": "{service_name}",
        "variables": [variable("service_name", "متن پست", "متن دلخواه پست.", "پیام جدید ما")],
    },
}


def template_variables(definitions: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return safe, documented variables belonging to one template only."""
    return [item for item in (definitions or []) if isinstance(item, dict) and item.get("key")]


def missing_required_variables(definitions: Iterable[dict[str, Any]], values: dict[str, str]) -> list[dict[str, Any]]:
    return [item for item in template_variables(definitions) if item.get("required", True) and not str(values.get(str(item["key"]), "")).strip()]


def render_template(body: str, values: dict[str, str], definitions: Iterable[dict[str, Any]] | None = None) -> str:
    """Render documented variables; leave unknown or undocumented braces literal."""
    allowed = {str(item["key"]) for item in template_variables(definitions)} if definitions is not None else set(values)
    return _VARIABLE.sub(lambda match: str(values.get(match.group(1), "")).strip() if match.group(1) in allowed else match.group(0), body).strip()


def variable_assignment_text(definitions: Iterable[dict[str, Any]]) -> str:
    return "\n".join(f"{item['key']}=" for item in template_variables(definitions))


def create_draft_from_template(template: ChannelContentTemplate, channel_id: int, values: dict[str, str]) -> ChannelContent:
    missing = missing_required_variables(template.variable_definitions, values)
    if missing:
        raise ValueError("مقدار متغیرهای ضروری وارد نشده است: " + "، ".join(str(item["label"]) for item in missing))
    return ChannelContent(channel_id=channel_id, title=template.title, content_type="text", status="draft", body=render_template(template.body, values, template.variable_definitions))
