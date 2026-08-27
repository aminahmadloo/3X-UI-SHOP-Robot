from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.customer_level import LEVELS, get_customer_level
from app.bot.utils.navigation import NavMain
from app.db.models import User

router = Router(name=__name__)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)]])


@router.callback_query(F.data == NavMain.CUSTOMER_LEVEL)
async def customer_level(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    level, count = await get_customer_level(session, user.tg_id)
    next_level = next((item for item in LEVELS if item.min_purchases > count), None)

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

    lines.extend([
        "📊 <b>راهنمای سطوح:</b>",
        "⚪ سطح پایه: ۰ تا ۴ خرید — بدون تخفیف" + (" ← شما اینجایید" if level.key == "bronze" else ""),
        "🔩 سطح برنزی: ۵ تا ۱۰ خرید — ۱۰٪ تخفیف" + (" ← شما اینجایید" if level.key == "silver" else ""),
        "⚙️ سطح نقره‌ای: ۱۱ تا ۲۰ خرید — ۱۵٪ تخفیف" + (" ← شما اینجایید" if level.key == "gold" else ""),
        "👑 سطح طلایی: ۲۱+ خرید — ۲۰٪ تخفیف" + (" ← شما اینجایید" if level.key == "platinum" else ""),
    ])

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_keyboard())
