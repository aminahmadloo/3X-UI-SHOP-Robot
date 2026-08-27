from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.customer_level import get_customer_level, get_customer_levels
from app.bot.utils.navigation import NavMain
from app.db.models import User

router = Router(name=__name__)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)]])


def _level_guide_line(level, current_key: str) -> str:
    if level.max_purchases is None:
        purchases = f"{level.min_purchases}+"
    else:
        purchases = f"{level.min_purchases} تا {level.max_purchases}"
    current = " ← شما اینجایید" if level.key == current_key else ""
    discount = "بدون تخفیف" if level.discount_percent == 0 else f"{level.discount_percent}% تخفیف"
    icons = {"bronze": "⚪️", "silver": "🔩", "gold": "⚙️", "platinum": "👑"}
    return f"{icons[level.key]} {level.title}: {purchases} خرید — {discount}{current}"


@router.callback_query(F.data == NavMain.CUSTOMER_LEVEL)
async def customer_level(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    level, count = await get_customer_level(session, user.tg_id)
    levels = await get_customer_levels(session)
    next_level = next((item for item in levels if item.min_purchases > count), None)

    lines = [
        f"🏆 <b>سطح شما: {level.title}</b>",
        "",
        f"🛒 تعداد خرید: <b>{count}</b> عدد",
        f"🎁 تخفیف ثابت: <b>{level.discount_percent}%</b>",
        "",
    ]
    if next_level:
        lines.extend([
            f"📈 <b>سطح بعدی: {next_level.title}</b>",
            f"تا رسیدن به سطح بعدی: <b>{next_level.min_purchases - count}</b> خرید دیگر",
            f"تخفیف سطح بعدی: <b>{next_level.discount_percent}%</b>",
            "",
        ])
    else:
        lines.extend(["📈 <b>بالاترین سطح را دارید.</b>", ""])

    lines.append("📊 <b>راهنمای سطوح:</b>")
    lines.extend(_level_guide_line(item, level.key) for item in levels)

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_keyboard())
