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
from app.db.models import CustomServicePricing, Invite, Referral, User, WalletTopupAmount

from .keyboard import main_menu_keyboard
from app.bot.routers.misc.keyboard import back_to_main_menu_button
from .wallet_keyboard import wallet_keyboard

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


async def send_main_menu(
    bot: Bot,
    user: User,
    services: ServicesContainer,
    config: Config,
    state: FSMContext,
    session: AsyncSession,
) -> Message:
    """Send the same main menu used by /start for an existing user."""
    is_admin = await IsAdmin()(user_id=user.tg_id)
    pricing = await CustomServicePricing.get_or_create(session)

    reply_markup = main_menu_keyboard(
        is_admin,
        is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
        is_trial_available=await services.subscription.is_trial_available(user),
        is_referred_trial_available=await services.referral.is_referred_trial_available(user),
        show_custom_service_button=pricing.show_custom_service_button,
    )

    main_menu = await bot.send_message(
        chat_id=user.tg_id,
        text=(
            f"🌀 <b>{user.first_name} عزیز، به ToonelVPN خوش آمدی</b> 🌐\n\n"
            "⚡️ اتصال سریع، پایدار و مطمئن به اینترنت آزاد، با سرویس‌هایی متناسب با نیازت.\n\n"
            "🚀 سرویس‌های متنوع برای استفاده روزمره\n"
            "🌍 سرورهای مختلف برای انتخاب بهتر\n"
            "🛡️ اتصال پایدار و مطمئن\n"
            "💻 سازگار با دستگاه‌های مختلف\n"
            "🔄 خرید، تمدید و مدیریت آسان سرویس\n"
            "──────────────────\n\n"
            "🎁 <b>برای شروع، می‌تونی اکانت تست رو امتحان کنی.</b>\n\n"
            "✨ <b>یکی از گزینه‌های زیر رو انتخاب کن:</b> 👇"
        ),
        reply_markup=reply_markup,
    )
    await state.update_data({MAIN_MESSAGE_ID_KEY: main_menu.message_id})
    return main_menu



class _DeepLinkCallbackAdapter:
    """Minimal CallbackQuery-compatible adapter for /start deep links.

    Existing callback handlers only need callback.answer(), callback.message
    and occasionally callback.bot. No existing callback handler is modified.
    """

    def __init__(self, message: Message, bot: Bot) -> None:
        self.message = message
        self.bot = bot

    async def answer(self, *args, **kwargs) -> None:
        return None


async def _handle_main_menu_deep_link(
    payload: str,
    message: Message,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
    config: Config,
    session: AsyncSession,
) -> bool:
    """Open an existing main-menu section from a Telegram /start payload.

    Returns True when the payload belongs to a supported main-menu section.
    Existing referral/invite payload handling remains completely separate.
    """
    handlers = {
        "buy": "buy",
        "custom_service": "custom_service",
        "renew": "renew",
        "my_services": "my_services",
        "profile": "profile",
        "wallet": "wallet",
        "referral": "referral",
        "customer_level": "customer_level",
        "trial": "trial",
        "support": "support",
    }

    if payload not in handlers:
        return False

    # The main menu message is the target message that existing callback
    # handlers normally edit after a button press.
    main_menu = await send_main_menu(
        bot=message.bot,
        user=user,
        services=services,
        config=config,
        state=state,
        session=session,
    )

    callback = _DeepLinkCallbackAdapter(
        message=main_menu,
        bot=message.bot,
    )

    route = handlers[payload]

    if route == "buy":
        from app.bot.routers.subscription.dynamic_service_purchase_handler import (
            _show,
        )

        await _show(callback, session, user)

    elif route == "custom_service":
        await callback_custom_service(callback, session)

    elif route == "renew":
        from app.bot.routers.main_menu.renew_service_handler import (
            entry as renew_entry,
        )

        await renew_entry(
            callback=callback,
            user=user,
            session=session,
            services=services,
            state=state,
        )

    elif route == "my_services":
        from app.bot.routers.my_services.handler import (
            callback_my_services,
        )

        await callback_my_services(
            callback=callback,
            user=user,
            session=session,
            services=services,
        )

    elif route == "profile":
        from app.bot.routers.profile.handler import (
            callback_profile,
        )

        await callback_profile(
            callback=callback,
            user=user,
            services=services,
            state=state,
            session=session,
        )

    elif route == "wallet":
        await callback_wallet(
            callback=callback,
            user=user,
            services=services,
            session=session,
        )

    elif route == "referral":
        from app.bot.routers.referral.handler import (
            callback_referral,
        )

        await callback_referral(
            callback=callback,
            user=user,
            state=state,
            session=session,
            config=config,
        )

    elif route == "customer_level":
        from app.bot.routers.customer_level.handler import (
            customer_level,
        )

        await customer_level(
            callback=callback,
            user=user,
            session=session,
        )

    elif route == "trial":
        from app.bot.routers.subscription.trial_handler import (
            callback_get_trial,
        )

        await callback_get_trial(
            callback=callback,
            user=user,
            state=state,
            services=services,
        )

    elif route == "support":
        from app.bot.routers.support.handler import (
            callback_support,
        )

        await callback_support(
            callback=callback,
            state=state,
        )

    return True


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

    # /start must ALWAYS reset the FSM.
    # This prevents stale states such as waiting_days from
    # intercepting /start and treating it as a numeric input.
    previous_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    await state.clear()

    if previous_message_id:
        try:
            await message.bot.delete_message(chat_id=user.tg_id, message_id=previous_message_id)
            logger.debug(f"Main message for user {user.tg_id} deleted.")
        except Exception as exception:
            logger.error(f"Failed to delete main message for user {user.tg_id}: {exception}")

    # Telegram Deep Links arrive as: /start <payload>.
    # Handle only our reserved main-menu payloads here.
    # Referral/invite payloads below remain unchanged.
    if command.args:
        deep_link_payload = command.args.strip().lower()

        if await _handle_main_menu_deep_link(
            payload=deep_link_payload,
            message=message,
            user=user,
            state=state,
            services=services,
            config=config,
            session=session,
        ):
            return

    if command.args and is_new_user:
        referral_arg = command.args.strip()

        # Referral links use: /start ref_<telegram_user_id>
        if referral_arg.startswith("ref_"):
            referrer_id_raw = referral_arg[4:].strip()

            if referrer_id_raw.isdigit():
                await process_creating_referral(
                    session=session,
                    user=user,
                    referrer_id=int(referrer_id_raw),
                )
            else:
                logger.warning(
                    "Invalid referral payload for user %s: %s",
                    user.tg_id,
                    referral_arg,
                )

        elif referral_arg.isdigit():
            # Backward compatibility with old /start <tg_id> links.
            await process_creating_referral(
                session=session,
                user=user,
                referrer_id=int(referral_arg),
            )

        else:
            await process_invite_attribution(
                session=session,
                user=user,
                invite_hash=referral_arg,
            )

    if is_new_user:
        is_admin = await IsAdmin()(user_id=user.tg_id)
        pricing = await CustomServicePricing.get_or_create(session)

        reply_markup = main_menu_keyboard(
            is_admin,
            is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
            is_trial_available=await services.subscription.is_trial_available(user),
            is_referred_trial_available=await services.referral.is_referred_trial_available(user),
            show_custom_service_button=pricing.show_custom_service_button,
        )
        main_menu = await send_main_menu(
            bot=message.bot,
            user=user,
            services=services,
            config=config,
            state=state,
            session=session,
        )
    else:
        main_menu = await send_main_menu(
            bot=message.bot,
            user=user,
            services=services,
            config=config,
            state=state,
            session=session,
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
            text=(f"🌀 <b>{user.first_name} عزیز، به ToonelVPN خوش آمدی</b> 🌐\n\n""⚡️ اتصال سریع، پایدار و مطمئن به اینترنت آزاد، با سرویس‌هایی متناسب با نیازت.\n\n""🚀 سرویس‌های متنوع برای استفاده روزمره\n""🌍 سرورهای مختلف برای انتخاب بهتر\n""🛡️ اتصال پایدار و مطمئن\n""💻 سازگار با دستگاه‌های مختلف\n""🔄 خرید، تمدید و مدیریت آسان سرویس\n""──────────────────\n\n""🎁 <b>برای شروع، می‌تونی اکانت تست رو امتحان کنی.</b>\n\n""✨ <b>یکی از گزینه‌های زیر رو انتخاب کن:</b> 👇"),
            reply_markup=main_menu_keyboard(
                is_admin,
                is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
                show_custom_service_button=(
                    await CustomServicePricing.get_or_create(session)
                ).show_custom_service_button,
                is_trial_available=await services.subscription.is_trial_available(user),
                is_referred_trial_available=await services.referral.is_referred_trial_available(user),
            ),
        )


@router.callback_query(F.data == NavMain.CUSTOM_SERVICE)
async def callback_custom_service(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    pricing = await CustomServicePricing.get_or_create(session)

    days = 30
    gigabytes = 40
    devices = 2
    days_cost = days * pricing.base_price_per_day
    gigabytes_cost = gigabytes * pricing.base_price_per_gb
    devices_cost = devices * pricing.base_price_per_device
    total = days_cost + gigabytes_cost + devices_cost

    text = (
        "👋 <b>کاربر گرامی</b> 🌟\n\n"
        "🛠️ در این بخش می‌توانید سرویس مورد نیاز خود را مطابق نیازتان شخصی‌سازی کرده و در کمتر از ۵ دقیقه آن را فعال و دریافت کنید. ⏱️\n\n"
        "🚀 <b>امکان خرید سرویس پرسرعت V2Ray با انتخاب دلخواه:</b>\n"
        "📅 تعداد روز\n"
        "📦 حجم مصرفی\n"
        "👥 تعداد کاربران\n\n"
        "📍 همچنین می‌توانید لوکیشن مورد نظر خود را انتخاب کنید؛ این امکان کاملاً رایگان است و هیچ هزینه اضافی ندارد. 🎁\n\n"
        "💰 <b>هزینه سرویس بر اساس فرمول زیر توسط ربات محاسبه می‌شود:</b>\n\n"
        f"📅 هر روز: <b>{pricing.base_price_per_day:,.0f} تومان</b>\n"
        f"📦 هر گیگابایت حجم: <b>{pricing.base_price_per_gb:,.0f} تومان</b>\n"
        f"👤 هر کاربر: <b>{pricing.base_price_per_device:,.0f} تومان</b>\n\n"
        "🧮 <b>مثال:</b> اگر بخواهید یک سرویس با مشخصات زیر انتخاب کنید:\n\n"
        f"📅 30 روز → 30 × {pricing.base_price_per_day:,.0f} = <b>{days_cost:,.0f} تومان</b>\n"
        f"📦 40 گیگابایت → 40 × {pricing.base_price_per_gb:,.0f} = <b>{gigabytes_cost:,.0f} تومان</b>\n"
        f"👥 2 کاربر → 2 × {pricing.base_price_per_device:,.0f} = <b>{devices_cost:,.0f} تومان</b>\n\n"
        f"💳 <b>مبلغ نهایی سرویس شما خواهد بود: {total:,.0f} تومان</b>\n\n"
        "👇 در صورتی که قصد خرید سرویس با مشخصات دلخواه خود را دارید، بر روی دکمه زیر کلیک کنید."
    )

    await callback.answer()
    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⭐️ خرید سرویس اختصاصی ⭐️",
                        callback_data="custom_service:buy",
                    )
                ],
                [
                    back_to_main_menu_button()
                ],
            ]
        ),
    )


@router.callback_query(F.data == "custom_service:buy")
async def callback_custom_service_buy(callback: CallbackQuery) -> None:
    await callback.answer("این بخش در مرحله بعد فعال می‌شود.", show_alert=True)


@router.callback_query(F.data == "main_menu:renew_service_placeholder")
async def callback_renew_service_placeholder(callback: CallbackQuery) -> None:
    await callback.answer(
        "📦 بخش سرویس های من به‌زودی فعال می‌شود.",
        show_alert=True,
    )


@router.callback_query(F.data == NavMain.WALLET)
async def callback_wallet(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    session: AsyncSession,
) -> None:
    logger.info(f"User {user.tg_id} opened wallet page.")
    await callback.answer()

    balance = await services.wallet.get_balance(user.tg_id)
    amounts = await WalletTopupAmount.get_all(session)

    if amounts:
        amount_lines = _("wallet:message:topup_options")
    else:
        amount_lines = _("wallet:message:no_topup_amounts")

    text = _("wallet:message:main").format(
        balance=f"{balance:,}",
        topup_options=amount_lines,
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=wallet_keyboard(amounts),
    )


@router.callback_query(F.data.regexp(r"^wallet:topup:\d+$"))
async def callback_wallet_topup(callback: CallbackQuery) -> None:
    logger.info(f"User selected wallet top-up amount: {callback.data}")
    await callback.answer(
        _("wallet:popup:payment_unavailable"),
        show_alert=True,
    )


@router.callback_query(F.data == NavMain.MAIN_MENU)
async def callback_main_menu(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    state: FSMContext,
    config: Config,
    session: AsyncSession,
) -> None:
    logger.info(f"User {user.tg_id} returned to main menu page.")
    await state.clear()
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    is_admin = await IsAdmin()(user_id=user.tg_id)
    await callback.message.delete()
    await send_main_menu(
        bot=callback.bot,
        user=user,
        services=services,
        config=config,
        state=state,
        session=session,
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

    is_admin = await IsAdmin()(user_id=user.tg_id)

    reply_markup = main_menu_keyboard(
        is_admin,
        is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
        is_trial_available=await services.subscription.is_trial_available(user),
        is_referred_trial_available=await services.referral.is_referred_trial_available(
            user
        ),
    )

    text = (
        f"🌀 <b>{user.first_name} عزیز، به ToonelVPN خوش آمدی</b> 🌐\n\n"
        "⚡️ اتصال سریع، پایدار و مطمئن به اینترنت آزاد، با سرویس‌هایی متناسب با نیازت.\n\n"
        "🚀 سرویس‌های متنوع برای استفاده روزمره\n"
        "🌍 سرورهای مختلف برای انتخاب بهتر\n"
        "🛡️ اتصال پایدار و مطمئن\n"
        "💻 سازگار با دستگاه‌های مختلف\n"
        "🔄 خرید، تمدید و مدیریت آسان سرویس\n"
        "──────────────────\n\n"
        "🎁 <b>برای شروع، می‌تونی اکانت تست رو امتحان کنی.</b>\n\n"
        "✨ <b>یکی از گزینه‌های زیر رو انتخاب کن:</b> 👇"
    )

    # If an FSM context is available, try to edit the existing main-menu message.
    if state is not None:
        try:
            main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)

            if main_message_id:
                try:
                    await bot.edit_message_text(
                        text=text,
                        chat_id=user.tg_id,
                        message_id=main_message_id,
                        reply_markup=reply_markup,
                    )
                    return
                except Exception as exception:
                    logger.warning(
                        f"Could not edit existing main menu message for user "
                        f"{user.tg_id}: {exception}"
                    )
        except Exception as exception:
            logger.warning(
                f"Could not read FSM main message ID for user "
                f"{user.tg_id}: {exception}"
            )

    # No usable FSM/message ID: send a fresh main-menu message.
    try:
        await bot.send_message(
            chat_id=user.tg_id,
            text=text,
            reply_markup=reply_markup,
        )
        logger.info(
            f"Sent fresh main menu message to user {user.tg_id}."
        )
    except Exception as exception:
        logger.error(
            f"Error sending fresh main menu to user {user.tg_id}: {exception}"
        )
