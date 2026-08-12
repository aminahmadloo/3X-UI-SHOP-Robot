import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.i18n import I18n, gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.utils.commands import set_user_commands
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY
from app.bot.utils.navigation import NavMain
from app.config import Config
from app.db.models import Invite, Referral, User

from .keyboard import main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def process_invite_attribution(session: AsyncSession, user: User, invite_hash: str) -> bool:
    logger.info(f"Checking invite {invite_hash} for user {user.tg_id}")
    try:
        invite = await Invite.get_by_hash(session=session, hash_code=invite_hash)
        if not invite or not invite.is_active:
            logger.info(f"Invalid or inactive invite hash: {invite_hash}")
            return False

        user.source_invite_name = invite.name
        await session.commit()
        await Invite.increment_clicks(session=session, invite_id=invite.id)
        logger.info(f"User {user.tg_id} attributed to invite {invite.name}")
        return True
    except Exception as exception:
        logger.critical(f"Invite attribution error for user {user.tg_id}: {exception}")
        return False


async def process_creating_referral(session: AsyncSession, user: User, referrer_id: int) -> bool:
    logger.info(f"Assigning user {user.tg_id} as a referred to a referrer user {referrer_id}")
    try:
        referrer = await User.get(session=session, tg_id=referrer_id)
        if not referrer or referrer.tg_id == user.tg_id:
            logger.info(
                f"Failed to assign user {user.tg_id} as referred to a referrer user {referrer_id}."
                f"Invalid string received."
            )
            return False

        await Referral.create(
            session=session, referrer_tg_id=referrer.tg_id, referred_tg_id=user.tg_id
        )
        logger.info(
            f"User {user.tg_id} assigned as referred to a referrer with tg id {referrer.tg_id}"
        )
        return True
    except Exception as exception:
        logger.critical(
            f"Referral creation error for {user.tg_id} (arg: {referrer_id}): {exception}"
        )
        return False


@router.message(Command(NavMain.START))
async def command_main_menu(
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
    config: Config,
    session: AsyncSession,
    command: CommandObject,
    is_new_user: bool,
) -> None:
    logger.info(f"User {user.tg_id} opened main menu page.")
    previous_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)

    if previous_message_id:
        try:
            await message.bot.delete_message(chat_id=user.tg_id, message_id=previous_message_id)
            logger.debug(f"Main message for user {user.tg_id} deleted.")
        except Exception as exception:
            logger.error(f"Failed to delete main message for user {user.tg_id}: {exception}")
        finally:
            await state.clear()

    if command.args and is_new_user:
        if command.args.isdigit():
            await process_creating_referral(
                session=session, user=user, referrer_id=int(command.args)
            )
        else:
            await process_invite_attribution(session=session, user=user, invite_hash=command.args)

    is_admin = await IsAdmin()(user_id=user.tg_id)
    main_menu = await message.answer(
        text=_("main_menu:message:main").format(name=user.first_name),
        reply_markup=main_menu_keyboard(
            is_admin,
            is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
            is_trial_available=await services.subscription.is_trial_available(user),
            is_referred_trial_available=await services.referral.is_referred_trial_available(user),
        ),
    )
    await state.update_data({MAIN_MESSAGE_ID_KEY: main_menu.message_id})


@router.callback_query(F.data == NavMain.LANGUAGE)
async def show_language_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "🌐 انتخاب زبان / Choose language / Выберите язык",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🇮🇷 فارسی", callback_data="language:fa"),
                    InlineKeyboardButton(text="🇬🇧 English", callback_data="language:en"),
                ],
                [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="language:ru")],
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)],
            ]
        ),
    )


@router.callback_query(F.data.regexp(r"^language:(fa|en|ru)$"))
async def change_language(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    config: Config,
    state: FSMContext,
) -> None:
    language = callback.data.split(":", 1)[1]

    await User.update(session=session, tg_id=user.tg_id, language_code=language)
    user.language_code = language

    await set_user_commands(callback.bot, user.tg_id, language)

    await callback.answer(
        "زبان با موفقیت تغییر کرد"
        if language == "fa"
        else "Language changed"
        if language == "en"
        else "Язык изменён"
    )

    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    is_admin = await IsAdmin()(user_id=user.tg_id)

    with I18n.get_current().use_locale(language):
        await callback.message.edit_text(
            text=_("main_menu:message:main").format(name=user.first_name),
            reply_markup=main_menu_keyboard(
                is_admin,
                is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
                is_trial_available=await services.subscription.is_trial_available(user),
                is_referred_trial_available=await services.referral.is_referred_trial_available(user),
            ),
        )


@router.callback_query(F.data == NavMain.CUSTOM_SERVICE)
async def callback_custom_service(callback: CallbackQuery) -> None:
    await callback.answer("🚧 خرید سرویس با مشخصات دلخواه به‌زودی فعال می‌شود.", show_alert=True)


@router.callback_query(F.data == NavMain.MY_SERVICES)
async def callback_my_services(callback: CallbackQuery) -> None:
    await callback.answer("📦 بخش سرویس های من به‌زودی فعال می‌شود.", show_alert=True)


@router.callback_query(F.data == NavMain.MAIN_MENU)
async def callback_main_menu(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    state: FSMContext,
    config: Config,
) -> None:
    logger.info(f"User {user.tg_id} returned to main menu page.")
    await state.clear()
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    is_admin = await IsAdmin()(user_id=user.tg_id)
    await callback.message.edit_text(
        text=_("main_menu:message:main").format(name=user.first_name),
        reply_markup=main_menu_keyboard(
            is_admin,
            is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
            is_trial_available=await services.subscription.is_trial_available(user),
            is_referred_trial_available=await services.referral.is_referred_trial_available(user),
        ),
    )


async def redirect_to_main_menu(
    bot: Bot,
    user: User,
    services: ServicesContainer,
    config: Config,
    storage: RedisStorage | None = None,
    state: FSMContext | None = None,
) -> None:
    logger.info(f"User {user.tg_id} redirected to main menu page.")

    if not state:
        state: FSMContext = FSMContext(
            storage=storage,
            key=StorageKey(bot_id=bot.id, chat_id=user.tg_id, user_id=user.tg_id),
        )

    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    is_admin = await IsAdmin()(user_id=user.tg_id)

    try:
        await bot.edit_message_text(
            text=_("main_menu:message:main").format(name=user.first_name),
            chat_id=user.tg_id,
            message_id=main_message_id,
            reply_markup=main_menu_keyboard(
                is_admin,
                is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
                is_trial_available=await services.subscription.is_trial_available(user),
                is_referred_trial_available=await services.referral.is_referred_trial_available(
                    user
                ),
            ),
        )
    except Exception as exception:
        logger.error(f"Error redirecting to main menu page: {exception}")
