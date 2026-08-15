from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.config import Config
from app.db.models import CardSettings

router = Router(name=__name__)


class CardSettingsState(StatesGroup):
    waiting_card_number = State()
    waiting_holder_name = State()


def menu_markup(settings: CardSettings) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✏️ ویرایش اطلاعات کارت", callback_data="cardsettings:edit")],
    ]
    if settings.is_active:
        rows.append([InlineKeyboardButton(text="🔴 غیرفعال کردن کارت به کارت", callback_data="cardsettings:disable")])
    else:
        rows.append([InlineKeyboardButton(text="🟢 فعال کردن کارت به کارت", callback_data="cardsettings:enable")])
    rows.append([InlineKeyboardButton(text="🗑 حذف اطلاعات کارت", callback_data="cardsettings:delete")])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_settings(session: AsyncSession, config: Config) -> CardSettings:
    return await CardSettings.get_or_create(
        session,
        card_number=config.shop.CARD_NUMBER or "",
    )


async def show_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await get_settings(session, config)
    status = "🟢 فعال" if settings.is_active else "🔴 غیرفعال"
    number = settings.card_number or "تنظیم نشده"
    holder = settings.card_holder_name or "تنظیم نشده"
    text = (
        "💳 <b>مدیریت کارت به کارت</b>\n\n"
        f"وضعیت: <b>{status}</b>\n\n"
        f"شماره کارت:\n<code>{number}</code>\n\n"
        f"صاحب کارت:\n<b>{holder}</b>"
    )
    await callback.message.edit_text(text, reply_markup=menu_markup(settings))


@router.callback_query(F.data == NavAdminTools.CARD_SETTINGS, IsAdmin())
async def card_settings_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    await show_menu(callback, session, config)


@router.callback_query(F.data == "cardsettings:edit", IsAdmin())
async def edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CardSettingsState.waiting_card_number)
    await callback.message.edit_text(
        "✏️ <b>ویرایش کارت به کارت</b>\n\n"
        "شماره کارت ۱۶ رقمی را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف", callback_data=NavAdminTools.CARD_SETTINGS)]
        ]),
    )


@router.message(CardSettingsState.waiting_card_number, IsAdmin())
async def receive_card_number(message: Message, state: FSMContext) -> None:
    number = (message.text or "").strip().replace(" ", "").replace("-", "")
    if not number.isdigit() or len(number) != 16:
        await message.answer("❌ شماره کارت باید دقیقاً ۱۶ رقم باشد. دوباره وارد کنید.")
        return
    await state.update_data(card_number=number)
    await state.set_state(CardSettingsState.waiting_holder_name)
    await message.answer(
        "👤 <b>نام و نام خانوادگی صاحب کارت</b> را وارد کنید:\n\n"
        "مثال: <code>امین احمدلو</code>"
    )


@router.message(CardSettingsState.waiting_holder_name, IsAdmin())
async def receive_holder_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    holder = " ".join((message.text or "").strip().split())
    if len(holder) < 3:
        await message.answer("❌ نام و نام خانوادگی معتبر نیست. دوباره وارد کنید.")
        return
    data = await state.get_data()
    settings = await CardSettings.get_or_create(session)
    settings.card_number = data["card_number"]
    settings.card_holder_name = holder
    settings.is_active = True
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ <b>اطلاعات کارت با موفقیت ذخیره شد.</b>\n\n"
        f"💳 شماره کارت: <code>{settings.card_number}</code>\n"
        f"👤 صاحب کارت: <b>{settings.card_holder_name}</b>\n"
        "🟢 وضعیت: فعال"
    )


@router.callback_query(F.data == "cardsettings:disable", IsAdmin())
async def disable_card(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await get_settings(session, config)
    settings.is_active = False
    await session.commit()
    await callback.answer("🔴 کارت به کارت غیرفعال شد.", show_alert=True)
    await show_menu(callback, session, config)


@router.callback_query(F.data == "cardsettings:enable", IsAdmin())
async def enable_card(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await get_settings(session, config)
    if not settings.card_number or not settings.card_holder_name:
        await callback.answer("❌ ابتدا اطلاعات کارت را وارد کنید.", show_alert=True)
        return
    settings.is_active = True
    await session.commit()
    await callback.answer("🟢 کارت به کارت فعال شد.", show_alert=True)
    await show_menu(callback, session, config)


@router.callback_query(F.data == "cardsettings:delete", IsAdmin())
async def delete_card(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await get_settings(session, config)
    settings.card_number = ""
    settings.card_holder_name = ""
    settings.is_active = False
    await session.commit()
    await callback.answer("🗑 اطلاعات کارت حذف و کارت به کارت غیرفعال شد.", show_alert=True)
    await show_menu(callback, session, config)
