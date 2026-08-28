import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.models import ServicesContainer
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY, PREVIOUS_CALLBACK_KEY
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import User

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
