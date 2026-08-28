import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.models import ServicesContainer
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY, PREVIOUS_CALLBACK_KEY
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import TestAccount, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data == NavSubscription.GET_TRIAL)
async def callback_get_trial(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info("User %s requested a test account.", user.tg_id)
    await state.update_data({PREVIOUS_CALLBACK_KEY: NavMain.MAIN_MENU})
    await callback.answer()

    # Always check the latest database state before attempting to create
    # a test account. The User object injected into the handler may be stale.
    async with services.test_account.session_factory() as session:
        fresh_user = await User.get(session=session, tg_id=user.tg_id)
        existing_test = await TestAccount.get_by_telegram_id(session, user.tg_id)

    already_used = bool(
        fresh_user and fresh_user.is_trial_used
    ) or bool(
        existing_test
        and existing_test.status in {"active", "deleted", "pending"}
    )

    if already_used:
        await services.notification.notify_by_id(
            chat_id=user.tg_id,
            text=(
                "⚠️ شما یکبار اکانت تست رایگان دریافت کردید.\n"
                "هر کاربر فقط یکبار می‌تواند اکانت تست دریافت کند."
            ),
            duration=5,
        )
        logger.info(
            "User %s attempted to request a second test account; request denied.",
            user.tg_id,
        )
        return

    result = await services.test_account.create_test_account(user)
    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)

    if result is None:
        async with services.test_account.session_factory() as session:
            settings = await services.test_account.get_settings(session)

        if not settings.enabled:
            text = "❌ در حال حاضر اکانت تست غیرفعال است."
        elif user.is_trial_used:
            text = "❌ شما قبلاً از اکانت تست استفاده کرده‌اید و امکان دریافت مجدد آن وجود ندارد."
        else:
            text = "❌ امکان ساخت اکانت تست در حال حاضر وجود ندارد. لطفاً کمی بعد دوباره تلاش کنید."

        await services.notification.show_popup(callback=callback, text=text)
        return

    subscription_key, _record = result
    text = f"🎁 <b>لینک اشتراک اکانت تست:</b>\n\n<code>{subscription_key}</code>"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 لینک اشتراک تست", url=subscription_key)],
        ]
    )

    if main_message_id:
        await callback.bot.edit_message_text(
            text=text,
            chat_id=callback.message.chat.id,
            message_id=main_message_id,
            reply_markup=markup,
        )
    else:
        await callback.message.edit_text(text=text, reply_markup=markup)
