from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import CustomerLevelSettings

router = Router(name=__name__)


class CustomerLevelSettingsStates(StatesGroup):
    waiting_percent = State()


FIELDS = {
    "base": ("میخ آهنی", "base_discount_percent"),
    "bronze": ("میخ فولادی", "bronze_discount_percent"),
    "silver": ("میخ تیتانیومی", "silver_discount_percent"),
    "gold": ("میخ طلایی", "gold_discount_percent"),
}


def _keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔩 میخ آهنی", callback_data="customer_level_settings:edit:base")],
        [InlineKeyboardButton(text="⚙️ میخ فولادی", callback_data="customer_level_settings:edit:bronze")],
        [InlineKeyboardButton(text="✨ میخ تیتانیومی", callback_data="customer_level_settings:edit:silver")],
        [InlineKeyboardButton(text="👑 میخ طلایی", callback_data="customer_level_settings:edit:gold")],
        [InlineKeyboardButton(text="🔄 بازخوانی مقادیر", callback_data=NavAdminTools.CUSTOMER_LEVEL_SETTINGS)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _text(session: AsyncSession) -> str:
    settings = await CustomerLevelSettings.get_or_create(session)
    return (
        "🏆 <b>مدیریت تخفیف سطوح مشتری</b>\n\n"
        f"🔩 میخ آهنی: <b>{settings.base_discount_percent}%</b>\n"
        f"⚙️ میخ فولادی: <b>{settings.bronze_discount_percent}%</b>\n"
        f"✨ میخ تیتانیومی: <b>{settings.silver_discount_percent}%</b>\n"
        f"👑 میخ طلایی: <b>{settings.gold_discount_percent}%</b>\n\n"
        "برای تغییر درصد هر سطح، روی همان سطح بزنید.\n"
        "درصد تخفیف هر سطح پویاست و مقدار آن باید عددی بین ۰ تا ۱۰۰ باشد."
    )


@router.callback_query(F.data == NavAdminTools.CUSTOMER_LEVEL_SETTINGS, IsAdmin())
async def show_customer_level_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(await _text(session), reply_markup=_keyboard())


@router.callback_query(F.data.startswith("customer_level_settings:edit:"), IsAdmin())
async def edit_customer_level_setting(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    key = callback.data.rsplit(":", 1)[-1]
    if key not in FIELDS:
        await callback.answer("مقدار نامعتبر است.", show_alert=True)
        return

    title, _ = FIELDS[key]
    await state.update_data(level_key=key)
    await state.set_state(CustomerLevelSettingsStates.waiting_percent)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>ویرایش تخفیف {title}</b>\n\n"
        "درصد تخفیف جدید را وارد کنید.\n"
        "مثلاً: <code>10</code>\n\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


@router.message(CustomerLevelSettingsStates.waiting_percent, IsAdmin())
async def save_customer_level_setting(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (message.text or "").strip().replace("٪", "%")
    if raw.endswith("%"):
        raw = raw[:-1].strip()

    try:
        value = int(raw)
        if not 0 <= value <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح بین ۰ تا ۱۰۰ وارد کنید.")
        return

    data = await state.get_data()
    key = data.get("level_key")
    if key not in FIELDS:
        await state.clear()
        await message.answer("❌ سطح مشتری نامعتبر است.")
        return

    title, field = FIELDS[key]
    settings = await CustomerLevelSettings.get_or_create(session)
    setattr(settings, field, value)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>تخفیف {title} با موفقیت ذخیره شد.</b>\n\n"
        f"درصد تخفیف جدید: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )
