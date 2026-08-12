import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.i18n import gettext as _

from app.bot.models import ClientData, ServicesContainer, SubscriptionData
from app.bot.routers.download.keyboard import platforms_keyboard
from app.bot.routers.profile.handler import prepare_message
from app.bot.routers.profile.keyboard import buy_subscription_keyboard, profile_keyboard
from app.bot.routers.referral.handler import generate_referral_summary_text
from app.bot.routers.referral.keyboard import referral_keyboard
from app.bot.routers.subscription.keyboard import subscription_keyboard
from app.bot.routers.support.keyboard import support_keyboard
from app.bot.utils.constants import PREVIOUS_CALLBACK_KEY
from app.bot.utils.navigation import NavDownload, NavMain, NavSubscription
from app.config import Config
from app.db.models import User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def _get_client_data(user: User, services: ServicesContainer) -> ClientData | None:
    if not user.server_id:
        return None

    client_data = await services.vpn.get_client_data(user)
    if client_data is None:
        logger.warning(f"No active VPN client data for user {user.tg_id}.")
    return client_data


@router.message(Command("profile"))
async def command_profile(
    message: Message,
    user: User,
    services: ServicesContainer,
) -> None:
    client_data = await _get_client_data(user, services)
    reply_markup = (
        profile_keyboard()
        if client_data and not client_data.has_subscription_expired
        else buy_subscription_keyboard()
    )
    await message.answer(
        text=await prepare_message(user=user, client_data=client_data),
        reply_markup=reply_markup,
    )


@router.message(Command("subscription"))
async def command_subscription(
    message: Message,
    user: User,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    client_data = await _get_client_data(user, services)
    callback_data = SubscriptionData(state=NavSubscription.PROCESS, user_id=user.tg_id)
    await state.update_data({PREVIOUS_CALLBACK_KEY: NavSubscription.MAIN})

    if client_data:
        if client_data.has_subscription_expired:
            text = _("subscription:message:expired")
        else:
            text = _("subscription:message:active").format(
                devices=client_data.max_devices,
                expiry_time=client_data.expiry_time,
            )
    else:
        text = _("subscription:message:not_active")

    await message.answer(
        text=text,
        reply_markup=subscription_keyboard(
            has_subscription=client_data,
            callback_data=callback_data,
        ),
    )


@router.message(Command("support"))
async def command_support(message: Message, config: Config) -> None:
    await message.answer(
        text=_("support:message:main"),
        reply_markup=support_keyboard(config.bot.SUPPORT_ID),
    )


@router.message(Command("download"))
async def command_download(message: Message, state: FSMContext) -> None:
    await state.update_data({PREVIOUS_CALLBACK_KEY: NavMain.MAIN_MENU})
    await message.answer(
        text=_("download:message:choose_platform"),
        reply_markup=platforms_keyboard(NavMain.MAIN_MENU),
    )


@router.message(Command("referral"))
async def command_referral(
    message: Message,
    user: User,
    session,
    config: Config,
) -> None:
    bot_username = (await message.bot.get_me()).username
    await message.answer(
        text=await generate_referral_summary_text(
            session=session,
            user=user,
            config=config,
            bot_username=bot_username,
        ),
        reply_markup=referral_keyboard(),
    )
