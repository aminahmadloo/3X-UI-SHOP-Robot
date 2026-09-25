import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.models import ServicesContainer
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY, PREVIOUS_CALLBACK_KEY
from app.bot.utils.jalali import format_jalali
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

    if not await services.test_account.is_test_account_available(user):
        await services.notification.notify_by_id(
            chat_id=user.tg_id,
            text=(
                "⚠️ شما قبلاً اکانت تست دریافت کرده‌اید و در حال حاضر امکان "
                "دریافت اکانت تست جدید برای شما فعال نیست.\n\n"
                "اگر استفاده مجدد برای حساب شما مجاز باشد، پس از پایان زمان انتظار "
                "می‌توانید دوباره درخواست کنید."
            ),
            duration=5,
        )
        logger.info(
            "User %s attempted to request an unavailable test account.",
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

    subscription_key, record = result

    quota_mb = max(1, round(record.quota_bytes / services.test_account.BYTES_PER_MB))
    duration_hours = max(
        1,
        round((record.expires_at - record.created_at).total_seconds() / 3600),
    )
    if duration_hours % 24 == 0:
        duration_text = f"{duration_hours // 24} روز"
    else:
        duration_text = f"{duration_hours} ساعت"

    text = (
        "🎁 <b>اکانت تست شما با موفقیت ایجاد شد.</b>\n\n"
        f"📦 حجم: <b>{quota_mb} مگابایت</b>\n"
        f"⏱ مدت اعتبار: <b>{duration_text}</b>\n"
        f"📅 تاریخ انقضا: <b>{format_jalali(record.expires_at)}</b>\n\n"
        f"🔗 <b>لینک اشتراک:</b>\n"
        f"<code>{subscription_key}</code>"
    )
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
