"""Safe, small template renderer for Telegram channel posts."""
from __future__ import annotations

import re

TEMPLATE_DEFINITIONS = {
    "special_offer": ("فروش ویژه", "🔥 <b>{service_name}</b>\n\n📦 حجم: {volume}\n⏳ مدت: {duration}\n💰 قیمت ویژه: <b>{price}</b>\n🎁 تخفیف: {discount}\n\n{buy_link}"),
    "server_notice": ("اطلاعیه سرور", "⚡ <b>اطلاعیه سرور</b>\n\n{service_name}\n\nپشتیبانی: {support_link}"),
    "maintenance": ("قطعی و تعمیرات", "🛠 <b>تعمیرات برنامه‌ریزی‌شده</b>\n\n{service_name}\n⏳ مدت تقریبی: {duration}\n\nپشتیبانی: {support_link}"),
    "referral": ("معرفی دوستان", "🎯 <b>دوستانت را دعوت کن</b>\n\n{discount}\n\n{buy_link}"),
    "renewal": ("تمدید سرویس", "🔄 <b>وقت تمدید سرویس است</b>\n\n{service_name}\n📦 {volume} / {duration}\n💰 {price}\n\n{buy_link}"),
    "custom": ("سفارشی", "{service_name}"),
}
_VARIABLE = re.compile(r"\{(service_name|volume|duration|price|buy_link|support_link|discount)\}")


def render_template(body: str, values: dict[str, str]) -> str:
    """Replace supported variables only; unknown braces remain literal."""
    return _VARIABLE.sub(lambda match: str(values.get(match.group(1), "")).strip(), body).strip()
