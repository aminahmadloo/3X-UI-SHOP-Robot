import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from babel.dates import format_datetime

from app.bot.models import ClientData
from app.bot.services import ServicesContainer
from app.bot.utils.constants import PREVIOUS_CALLBACK_KEY, TransactionStatus
from app.bot.utils.navigation import NavProfile
from app.db.models import User

from .keyboard import buy_subscription_keyboard, profile_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def prepare_message(
    user: User,
    client_data: ClientData | None,
    wallet_balance: int = 0,
) -> str:
    profile = _("profile:message:main").format(name=user.first_name, id=user.tg_id)

    if not client_data:
        purchased_services_count = sum(
            1
            for transaction in user.transactions
            if transaction.status == TransactionStatus.COMPLETED
        )
        tehran_now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
        current_datetime = format_datetime(
            tehran_now,
            "EEEE d MMMM yyyy — HH:mm:ss",
            locale="fa_IR",
        )
        return (
            f"{profile}\n\n"
            f"💰 موجودی کیف پول: {wallet_balance:,} تومان\n"
            f"🛍️ تعداد سرویس‌های خریداری‌شده: {purchased_services_count}\n\n"
            f"شما هنوز هیچ سرویسی خریداری نکرده‌اید.\n\n"
            f"📅 {current_datetime}"
        )

    subscription = _("profile:message:subscription").format(devices=client_data.max_devices)

    subscription += (
        _("profile:message:subscription_expiry_time").format(expiry_time=client_data.expiry_time)
        if not client_data.has_subscription_expired
        else _("profile:message:subscription_expired")
    )

    statistics = _("profile:message:statistics").format(
        total=client_data.traffic_used,
        up=client_data.traffic_up,
        down=client_data.traffic_down,
    )

    return profile + subscription + statistics


@router.callback_query(F.data == NavProfile.MAIN)
async def callback_profile(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    logger.info(f"User {user.tg_id} opened profile page.")
    await callback.answer()
    await state.update_data({PREVIOUS_CALLBACK_KEY: NavProfile.MAIN})

    client_data = None
    if user.server_id:
        client_data = await services.vpn.get_client_data(user)
        if client_data is None:
            logger.warning(
                f"No active VPN client data for user {user.tg_id}; showing profile without subscription."
            )

    reply_markup = (
        profile_keyboard()
        if client_data and not client_data.has_subscription_expired
        else buy_subscription_keyboard()
    )
    wallet_balance = await services.wallet.get_balance(user.tg_id)

    await callback.message.edit_text(
        text=await prepare_message(
            user=user,
            client_data=client_data,
            wallet_balance=wallet_balance,
        ),
        reply_markup=reply_markup,
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
    key_text = _("profile:message:key")
    message = await callback.message.answer(key_text.format(key=key, seconds_text=_("10 seconds")))

    for seconds in range(9, 0, -1):
        seconds_text = _("1 second", "{} seconds", seconds).format(seconds)
        await asyncio.sleep(1)
        await message.edit_text(text=key_text.format(key=key, seconds_text=seconds_text))
    await message.delete()
