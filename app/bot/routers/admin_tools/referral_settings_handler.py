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
    waiting_percent = State()


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش درصد پاداش", callback_data="referral_settings:edit")],
            [InlineKeyboardButton(text="🔄 بازخوانی مقدار", callback_data=NavAdminTools.REFERRAL_SETTINGS)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
    )


async def _text(session: AsyncSession) -> str:
    settings = await ReferralSettings.get_or_create(session)
    return (
        "🎁 <b>تنظیمات معرفی به دوستان</b>\n\n"
        f"💰 درصد پاداش خرید موفق: <b>{settings.reward_percent}%</b>\n\n"
        "این درصد از مبلغ هر خرید موفق فرد معرفی‌شده به کیف پول معرف واریز می‌شود.\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
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


@router.callback_query(F.data == "referral_settings:edit", IsAdmin())
async def edit_referral_setting(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReferralSettingsStates.waiting_percent)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش درصد پاداش معرفی</b>\n\n"
        "درصد جدید را وارد کنید.\n"
        "مثلاً: <code>30</code>\n\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


@router.message(ReferralSettingsStates.waiting_percent, IsAdmin())
async def save_referral_setting(
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

    settings = await ReferralSettings.get_or_create(session)
    settings.reward_percent = value
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>درصد پاداش معرفی با موفقیت ذخیره شد.</b>\n\n"
        f"درصد جدید: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )
