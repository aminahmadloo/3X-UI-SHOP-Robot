from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.customer_level import (
    get_customer_level,
    get_customer_levels,
    get_customer_points,
)
from app.bot.utils.navigation import NavMain
from app.db.models import User

router = Router(name=__name__)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)]])


def _level_guide_line(level, current_key: str) -> str:
    if level.max_points is None:
        points = f"{level.min_points}+"
    else:
        points = f"{level.min_points} تا {level.max_points}"
    current = " ← شما اینجایید" if level.key == current_key else ""
    discount = "بدون تخفیف" if level.discount_percent == 0 else f"{level.discount_percent}% تخفیف"
    icons = {"bronze": "🔩", "silver": "⚙️", "gold": "✨", "platinum": "👑"}
    return f"{icons[level.key]} {level.title}: {points} امتیاز — {discount}{current}"


@router.callback_query(F.data == NavMain.CUSTOMER_LEVEL)
async def customer_level(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    level, points = await get_customer_level(session, user.tg_id)
    levels = await get_customer_levels(session)
    _, purchase_count, _ = await get_customer_points(session, user.tg_id)
    next_level = next((item for item in levels if item.min_points > points), None)

    discount_text = (
        f"{level.discount_percent}%"
        if level.discount_percent > 0
        else f"ندارید ({level.title})"
    )

    lines = [
        f"⚡️ <b>سطح شما: {level.title}</b>",
        "",
        f"💳 تعداد خرید: <b>{purchase_count}</b>",
        f"⭐️ امتیاز شما: <b>{points}</b>",
        f"💰 تخفیف ثابت: <b>{discount_text}</b>",
        "",
    ]
    if next_level:
        lines.extend([
            f"📊 <b>سطح بعدی: {next_level.title}</b>",
            f"├ امتیاز لازم: <b>{next_level.min_points - points}</b> امتیاز دیگر",
            f"└ تخفیف سطح بعدی: {next_level.discount_percent}٪",
            "",
        ])
    else:
        lines.extend(["📊 <b>بالاترین سطح را دارید.</b>", ""])

    lines.extend([
        "✅ هر خرید موفق و هر دعوت موفق از دوستان، یک امتیاز برای شما دارد.",
        "پس فقط با خرید نه؛ با معرفی ربات به دوستانتان هم می‌توانید سطح خود را ارتقا دهید!",
        "",
        "📊 <b>راهنمای سطوح:</b>",
    ])
    lines.extend(_level_guide_line(item, level.key) for item in levels)

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_keyboard())
