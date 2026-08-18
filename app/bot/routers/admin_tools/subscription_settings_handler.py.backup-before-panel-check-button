from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.subscription_settings import SubscriptionSettingsStates
from app.bot.utils.navigation import NavAdminTools
from app.db.models import SubscriptionSettings

from .keyboard import subscription_settings_keyboard


router = Router(name=__name__)


async def settings_text(session: AsyncSession) -> str:
    settings = await SubscriptionSettings.get_or_create(session)

    return (
        "🌐 <b>مدیریت لینک اشتراک</b>\n\n"
        f"دامنه: <code>{settings.domain or 'IP سرور'}</code>\n"
        f"پورت: <code>{settings.port}</code>\n"
        f"مسیر: <code>{settings.path}</code>"
    )


@router.callback_query(
    F.data == NavAdminTools.SUBSCRIPTION_SETTINGS,
    IsAdmin()
)
async def subscription_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
):
    await callback.answer()

    await callback.message.edit_text(
        await settings_text(session),
        reply_markup=subscription_settings_keyboard(),
    )


@router.callback_query(
    F.data == "subscription_settings:domain",
    IsAdmin()
)
async def edit_domain(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    await state.set_state(
        SubscriptionSettingsStates.waiting_domain
    )

    await callback.message.edit_text(
        "🌐 دامنه جدید را ارسال کنید:"
    )


@router.message(
    SubscriptionSettingsStates.waiting_domain,
    IsAdmin(),
)
async def save_domain(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    settings = await SubscriptionSettings.get_or_create(session)

    settings.domain = (message.text or "").strip()

    await session.commit()
    await state.clear()

    await message.answer(
        "✅ دامنه ذخیره شد."
    )


@router.callback_query(
    F.data == "subscription_settings:port",
    IsAdmin()
)
async def edit_port(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    await state.set_state(
        SubscriptionSettingsStates.waiting_port
    )

    await callback.message.edit_text(
        "🔢 پورت جدید را ارسال کنید:"
    )


@router.message(
    SubscriptionSettingsStates.waiting_port,
    IsAdmin(),
)
async def save_port(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    try:
        port = int(message.text)
    except:
        await message.answer("❌ پورت نامعتبر است.")
        return

    settings = await SubscriptionSettings.get_or_create(session)

    settings.port = port

    await session.commit()
    await state.clear()

    await message.answer(
        "✅ پورت ذخیره شد."
    )


@router.callback_query(
    F.data == "subscription_settings:path",
    IsAdmin()
)
async def edit_path(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    await state.set_state(
        SubscriptionSettingsStates.waiting_path
    )

    await callback.message.edit_text(
        "📁 مسیر اشتراک جدید را ارسال کنید:"
    )


@router.message(
    SubscriptionSettingsStates.waiting_path,
    IsAdmin(),
)
async def save_path(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    settings = await SubscriptionSettings.get_or_create(session)

    settings.path = (message.text or "").strip()

    await session.commit()
    await state.clear()

    await message.answer(
        "✅ مسیر ذخیره شد."
    )
