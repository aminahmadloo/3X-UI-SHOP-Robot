import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ClientData, ServicesContainer
from app.bot.utils.constants import PREVIOUS_CALLBACK_KEY, TransactionStatus
from app.bot.utils.navigation import NavProfile
from app.db.models import User

from .keyboard import profile_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _profile_text(user: User, language: str, wallet_balance: int, purchased_services_count: int) -> str:
    balance = f"{wallet_balance:,}"

    if language == "en":
        return (
            "👤 <b>Account</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"👋 Hello <b>{user.first_name}</b>!\n\n"
            f"🆔 <b>Telegram ID:</b> <code>{user.tg_id}</code>\n\n"
            "📊 <b>Account Overview</b>\n"
            f"📦 Purchased services: <b>{purchased_services_count}</b>\n"
            f"💰 Wallet balance: <b>{balance} Toman</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "Manage your services, wallet, referrals and connection information from here."
        )

    if language == "ru":
        return (
            "👤 <b>Аккаунт</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"👋 Здравствуйте, <b>{user.first_name}</b>!\n\n"
            f"🆔 <b>Telegram ID:</b> <code>{user.tg_id}</code>\n\n"
            "📊 <b>Обзор аккаунта</b>\n"
            f"📦 Куплено сервисов: <b>{purchased_services_count}</b>\n"
            f"💰 Баланс кошелька: <b>{balance} томан</b>\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "Здесь вы можете управлять сервисами, кошельком, приглашениями и подключением."
        )

    return (
        "👤 <b>حساب کاربری</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"👋 سلام <b>{user.first_name}</b> عزیز!\n\n"
        f"🆔 <b>شناسه تلگرام:</b> <code>{user.tg_id}</code>\n\n"
        "📊 <b>خلاصه حساب</b>\n"
        f"📦 تعداد سرویس‌های خریداری‌شده: <b>{purchased_services_count}</b>\n"
        f"💰 موجودی کیف پول: <b>{balance} تومان</b>\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "از این بخش می‌توانید سرویس‌ها، کیف پول، دعوت دوستان و اطلاعات اتصال خود را مدیریت کنید."
    )


async def prepare_message(
    user: User,
    client_data: ClientData | None = None,
    wallet_balance: int = 0,
) -> str:
    """Backward-compatible profile message used by the /profile command.

    The account page is now rendered by ``callback_profile``.  This helper is
    intentionally kept because ``routers.commands`` still imports it.
    """
    purchased_services_count = sum(
        1 for transaction in user.transactions if transaction.status == TransactionStatus.COMPLETED
    )
    return _profile_text(
        user=user,
        language=user.language_code or "fa",
        wallet_balance=wallet_balance,
        purchased_services_count=purchased_services_count,
    )


@router.callback_query(F.data == NavProfile.MAIN)
async def callback_profile(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    logger.info(f"User {user.tg_id} opened account page.")
    await callback.answer()
    await state.update_data({PREVIOUS_CALLBACK_KEY: NavProfile.MAIN})

    purchased_services_count = sum(
        1 for transaction in user.transactions if transaction.status == TransactionStatus.COMPLETED
    )
    wallet_balance = await services.wallet.get_balance(user.tg_id)

    await callback.message.edit_text(
        text=_profile_text(
            user=user,
            language=user.language_code or "fa",
            wallet_balance=wallet_balance,
            purchased_services_count=purchased_services_count,
        ),
        reply_markup=profile_keyboard(user.language_code or "fa"),
    )


@router.callback_query(F.data == NavProfile.SHOW_KEY)
async def callback_show_key(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} looked key.")
    await callback.answer()
    key = await services.vpn.get_key(user)

    if user.language_code == "en":
        header = "🔑 <b>Connection Key</b>"
        seconds_template = "⏱️ This message will be deleted in {seconds} seconds."
    elif user.language_code == "ru":
        header = "🔑 <b>Ключ подключения</b>"
        seconds_template = "⏱️ Это сообщение будет удалено через {seconds} секунд."
    else:
        header = "🔑 <b>کلید اتصال</b>"
        seconds_template = "⏱️ این پیام تا {seconds} ثانیه دیگر حذف می‌شود."

    message = await callback.message.answer(
        f"{header}\n\n<code>{key}</code>\n\n{seconds_template.format(seconds=10)}"
    )

    for seconds in range(9, 0, -1):
        await asyncio.sleep(1)
        await message.edit_text(
            f"{header}\n\n<code>{key}</code>\n\n{seconds_template.format(seconds=seconds)}"
        )
    await message.delete()
