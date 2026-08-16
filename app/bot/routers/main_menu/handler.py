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
) -> Message:
    """Send the same main menu used by /start for an existing user."""
    is_admin = await IsAdmin()(user_id=user.tg_id)
    reply_markup = main_menu_keyboard(
        is_admin,
        is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
        is_trial_available=await services.subscription.is_trial_available(user),
        is_referred_trial_available=await services.referral.is_referred_trial_available(user),
    )

    main_menu = await bot.send_message(
        chat_id=user.tg_id,
        text=_("main_menu:message:main").format(name=user.first_name),
        reply_markup=reply_markup,
    )
    await state.update_data({MAIN_MESSAGE_ID_KEY: main_menu.message_id})
    return main_menu


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

    if is_new_user:
        is_admin = await IsAdmin()(user_id=user.tg_id)
        reply_markup = main_menu_keyboard(
            is_admin,
            is_referral_available=config.shop.REFERRER_REWARD_ENABLED,
            is_trial_available=await services.subscription.is_trial_available(user),
            is_referred_trial_available=await services.referral.is_referred_trial_available(user),
        )
        await message.answer(
            "v2ray 🔐: <b>توجه هرگز کلیک نکنید👇❗️❗️❗️❗️</b>\n\n"
            "❕❕❕❕❕❕❕❕❕\n"
            "تبلیغات نمایش داده شده در بالای پیوی ربات هیچگونه ارتباطی با تیم تونل وی پی ان ندارد و توسط تلگرام بدون هیچ نظارتی گذاشته می‌شود که تونل وی پی ان هیچگونه دسترسی جهت حذف آن ندارد.\n\n"
            "با توجه به این که هیچ نظارتی توسط تلگرام بر روی این تبلیغات وجود ندارد اکثرا کلاه برداری میباشد و ممکن است به جز عدم تحویل محصول به شما اطلاعات کارت شما به سرقت برود خواهشمندیم به هیچ وجه روی این تبلیغات کلیک نکنید عواقب آن بر عهده خود شما میباشد.\n\n"
            "<b>تاکنون تعدادی از مشتریان کلیک و خریداری کردند و از آنها کلاه برداری شده.</b>"
        )
        main_menu = await message.answer(
            "دسترسی سریع، پایدار و ایمن به اینترنت آزاد، تنها با چند کلیک!\n\n"
            "🔐 با استفاده از سرویس‌های پرسرعت V2Ray، بدون محدودیت و با کیفیت بالا به فضای وب متصل شوید — سازگار با تمامی گوشی‌ها (Android و iOS) و قابل استفاده برای خود و اطرافیانتان.\n\n"
            "💡 <b>چه چیزهایی در تونل وی پی ان منتظر شماست؟</b>\n"
            "• انتخاب از میان انواع پلن‌های متنوع و اقتصادی\n"
            "• خرید آسان و خودکار بدون نیاز به پشتیبانی دستی\n"
            "• دریافت فوری کانفیگ و آموزش اتصال\n"
            "• پشتیبانی حرفه‌ای و پاسخ‌گو\n\n"
            "برای مشاهده سرویس‌ها و شروع تجربه اینترنت آزاد، روی دکمه خرید سرویس کلیک کنید 👇\n\n"
            "📢 عضویت در کانال ما: @ToonelVpn",
            reply_markup=reply_markup,
        )
    else:
        main_menu = await send_main_menu(
            bot=message.bot,
            user=user,
            services=services,
            config=config,
            state=state,
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
                    InlineKeyboardButton(
                        text="🔙 بازگشت به منوی اصلی",
                        callback_data=NavMain.MAIN_MENU,
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "custom_service:buy")
async def callback_custom_service_buy(callback: CallbackQuery) -> None:
    await callback.answer("این بخش در مرحله بعد فعال می‌شود.", show_alert=True)


@router.callback_query(F.data == NavMain.MY_SERVICES)
async def callback_my_services(callback: CallbackQuery) -> None:
    await callback.answer("📦 بخش سرویس های من به‌زودی فعال می‌شود.", show_alert=True)


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
