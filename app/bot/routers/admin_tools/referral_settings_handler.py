from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ReferralSettings

router = Router(name=__name__)


class ReferralSettingsStates(StatesGroup):
    waiting_first_percent = State()
    waiting_repeat_percent = State()


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش پاداش خرید اول", callback_data="referral_settings:edit:first")],
            [InlineKeyboardButton(text="✏️ ویرایش پاداش خریدهای بعدی", callback_data="referral_settings:edit:repeat")],
            [InlineKeyboardButton(text="🔄 بازخوانی مقادیر", callback_data=NavAdminTools.REFERRAL_SETTINGS)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
    )


async def _text(session: AsyncSession) -> str:
    settings = await ReferralSettings.get_or_create(session)
    return (
        "🎁 <b>تنظیمات معرفی به دوستان</b>\n\n"
        f"🛒 پاداش خرید اول: <b>{settings.reward_percent}%</b>\n"
        f"🔄 پاداش خریدهای بعدی: <b>{settings.repeat_reward_percent}%</b>\n\n"
        "پاداش خرید اول فقط برای اولین خرید موفق هر فرد معرفی‌شده اعمال می‌شود.\n"
        "پاداش خریدهای بعدی از خرید دوم به بعد، مادام‌العمر اعمال می‌شود.\n\n"
        "هر دو نرخ کاملاً پویا هستند و از همین بخش قابل تغییرند.\n"
        "مقدار مجاز هر نرخ: ۰ تا ۱۰۰ درصد"
    )


@router.callback_query(F.data == NavAdminTools.REFERRAL_SETTINGS, IsAdmin())
async def show_referral_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(await _text(session), reply_markup=_keyboard())


@router.callback_query(F.data == "referral_settings:edit:first", IsAdmin())
async def edit_first_referral_setting(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReferralSettingsStates.waiting_first_percent)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش پاداش خرید اول</b>\n\n"
        "درصد جدید را وارد کنید.\n"
        "مثلاً: <code>30</code>\n\n"
        "این نرخ فقط برای اولین خرید موفق فرد معرفی‌شده استفاده می‌شود.\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


@router.callback_query(F.data == "referral_settings:edit:repeat", IsAdmin())
async def edit_repeat_referral_setting(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReferralSettingsStates.waiting_repeat_percent)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش پاداش خریدهای بعدی</b>\n\n"
        "درصد جدید را وارد کنید.\n"
        "مثلاً: <code>5</code>\n\n"
        "این نرخ از خرید دوم به بعد، مادام‌العمر استفاده می‌شود.\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


def _parse_percent(message: Message) -> int | None:
    raw = (message.text or "").strip().replace("٪", "%")
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    try:
        value = int(raw)
        if not 0 <= value <= 100:
            raise ValueError
    except ValueError:
        return None
    return value


@router.message(ReferralSettingsStates.waiting_first_percent, IsAdmin())
async def save_first_referral_setting(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    value = _parse_percent(message)
    if value is None:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح بین ۰ تا ۱۰۰ وارد کنید.")
        return

    settings = await ReferralSettings.get_or_create(session)
    settings.reward_percent = value
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>پاداش خرید اول با موفقیت ذخیره شد.</b>\n\n"
        f"نرخ جدید خرید اول: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )


@router.message(ReferralSettingsStates.waiting_repeat_percent, IsAdmin())
async def save_repeat_referral_setting(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    value = _parse_percent(message)
    if value is None:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح بین ۰ تا ۱۰۰ وارد کنید.")
        return

    settings = await ReferralSettings.get_or_create(session)
    settings.repeat_reward_percent = value
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>پاداش خریدهای بعدی با موفقیت ذخیره شد.</b>\n\n"
        f"نرخ جدید خریدهای بعدی: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )
