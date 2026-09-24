import asyncio
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.services import ServicesContainer
from app.bot.states.test_account_settings import TestAccountSettingsStates
from app.bot.tasks.test_account_cleanup import reschedule_cleanup
from app.bot.utils.navigation import NavAdminTools
from app.db.models import TestAccount, TestAccountSettings, User

router = Router(name=__name__)


async def _delete_message_after(
    bot: Bot,
    chat_id: int,
    message_id: int,
    delay: float = 5.0,
) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        # The message may already have been deleted or become unavailable.
        pass


def _schedule_delete(
    bot: Bot,
    chat_id: int,
    message_id: int,
    delay: float = 5.0,
) -> None:
    asyncio.create_task(
        _delete_message_after(bot, chat_id, message_id, delay)
    )


def _keyboard(settings: TestAccountSettings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        "🔴 غیرفعال کردن اکانت تست"
                        if settings.enabled
                        else "🟢 فعال کردن اکانت تست"
                    ),
                    callback_data="test_account_settings:toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 تغییر حجم تست",
                    callback_data="test_account_settings:volume",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏱ تغییر مدت تست",
                    callback_data="test_account_settings:duration",
                )
            ],
            [
                InlineKeyboardButton(
                    text="♻️ فاصله استفاده مجدد",
                    callback_data="test_account_settings:reuse_after_days",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕐 تغییر فاصله پاکسازی",
                    callback_data="test_account_settings:cleanup_interval",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 ریست استفاده برای همه",
                    callback_data="test_account_settings:reset_all",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 ریست استفاده یک کاربر",
                    callback_data="test_account_settings:reset_user",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧹 اجرای پاکسازی الان",
                    callback_data="test_account_settings:cleanup",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data=NavAdminTools.MAIN,
                )
            ],
        ]
    )


async def _render(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    settings = await TestAccountSettings.get_or_create(session)

    result = await session.execute(
        select(func.count(TestAccount.id))
    )
    total_used = int(result.scalar_one() or 0)

    result = await session.execute(
        select(func.count(TestAccount.id)).where(
            TestAccount.status == "active"
        )
    )
    active = int(result.scalar_one() or 0)

    status = "🟢 فعال" if settings.enabled else "🔴 غیرفعال"
    reset_text = (
        f"{settings.reset_at.strftime('%Y-%m-%d %H:%M')} UTC"
        if settings.reset_at
        else "ندارد"
    )

    text = (
        "🎁 <b>مدیریت اکانت تست</b>\n\n"
        f"وضعیت: {status}\n"
        f"حجم هر تست: <b>{settings.volume_mb} MB</b>\n"
        f"مدت هر تست: <b>{settings.duration_days} روز</b>\n"
        f"فاصله استفاده مجدد: <b>{settings.reuse_after_days} روز</b>\n"
        f"ریست سراسری: <b>{reset_text}</b>\n"
        f"پاکسازی خودکار: <b>هر {settings.cleanup_interval_hours} ساعت</b>\n\n"
        f"تعداد تست‌های ثبت‌شده: <b>{total_used}</b>\n"
        f"تست‌های فعال فعلی: <b>{active}</b>\n\n"
        "سابقه تست‌ها حفظ می‌شود. با تعیین فاصله استفاده مجدد، "
        "کاربر پس از گذشت آن مدت از آخرین تست می‌تواند دوباره تست بگیرد."
    )

    await callback.message.edit_text(
        text,
        reply_markup=_keyboard(settings),
    )


@router.callback_query(F.data == NavAdminTools.TEST_ACCOUNT_SETTINGS, IsAdmin())
async def open_test_account_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _render(callback, session)


@router.callback_query(
    F.data == "test_account_settings:toggle",
    IsAdmin(),
)
async def toggle_test_accounts(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    settings = await TestAccountSettings.get_or_create(session)
    settings.enabled = not settings.enabled

    await session.commit()

    await callback.answer("تنظیمات اکانت تست ذخیره شد.")
    await _render(callback, session)


@router.callback_query(
    F.data == "test_account_settings:volume",
    IsAdmin(),
)
async def edit_test_volume(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(
        TestAccountSettingsStates.waiting_volume_mb
    )
    await callback.answer()

    prompt = await callback.message.answer(
        "📦 <b>حجم اکانت تست</b>\n\n"
        "حجم جدید را بر حسب MB وارد کنید.\n"
        "مثلاً: <code>200</code>"
    )
    await state.update_data(
        prompt_message_id=prompt.message_id,
        prompt_chat_id=prompt.chat.id,
    )


@router.message(
    TestAccountSettingsStates.waiting_volume_mb,
    IsAdmin(),
)
async def save_test_volume(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    try:
        value = int((message.text or "").strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ مقدار نامعتبر است. "
            "یک عدد صحیح بزرگ‌تر از صفر بر حسب MB وارد کنید."
        )
        return

    state_data = await state.get_data()
    prompt_message_id = state_data.get("prompt_message_id")
    prompt_chat_id = state_data.get("prompt_chat_id")

    settings = await TestAccountSettings.get_or_create(session)
    settings.volume_mb = value

    await session.commit()
    await state.clear()

    confirmation = await message.answer(
        "✅ حجم اکانت تست ذخیره شد.",
        reply_markup=_keyboard(settings),
    )

    if prompt_message_id and prompt_chat_id:
        _schedule_delete(
            message.bot,
            prompt_chat_id,
            prompt_message_id,
            5.0,
        )

    _schedule_delete(
        message.bot,
        confirmation.chat.id,
        confirmation.message_id,
        5.0,
    )


@router.callback_query(
    F.data == "test_account_settings:duration",
    IsAdmin(),
)
async def edit_test_duration(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(
        TestAccountSettingsStates.waiting_duration_days
    )
    await callback.answer()

    prompt = await callback.message.answer(
        "⏱ <b>مدت اکانت تست</b>\n\n"
        "مدت جدید را بر حسب روز وارد کنید.\n"
        "مثلاً: <code>2</code>"
    )
    await state.update_data(
        prompt_message_id=prompt.message_id,
        prompt_chat_id=prompt.chat.id,
    )


@router.message(
    TestAccountSettingsStates.waiting_duration_days,
    IsAdmin(),
)
async def save_test_duration(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    try:
        value = int((message.text or "").strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ مقدار نامعتبر است. "
            "یک عدد صحیح بزرگ‌تر از صفر بر حسب روز وارد کنید."
        )
        return

    state_data = await state.get_data()
    prompt_message_id = state_data.get("prompt_message_id")
    prompt_chat_id = state_data.get("prompt_chat_id")

    settings = await TestAccountSettings.get_or_create(session)
    settings.duration_days = value

    await session.commit()
    await state.clear()

    confirmation = await message.answer(
        "✅ مدت اکانت تست ذخیره شد.",
        reply_markup=_keyboard(settings),
    )

    if prompt_message_id and prompt_chat_id:
        _schedule_delete(
            message.bot,
            prompt_chat_id,
            prompt_message_id,
            5.0,
        )

    _schedule_delete(
        message.bot,
        confirmation.chat.id,
        confirmation.message_id,
        5.0,
    )


@router.callback_query(
    F.data == "test_account_settings:cleanup_interval",
    IsAdmin(),
)
async def edit_cleanup_interval(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(
        TestAccountSettingsStates.waiting_cleanup_interval_hours
    )
    await callback.answer()

    prompt = await callback.message.answer(
        "🕐 <b>فاصله پاکسازی خودکار</b>\n\n"
        "فاصله اجرای پاکسازی را بر حسب ساعت وارد کنید.\n"
        "حداقل: <code>1</code> ساعت\n"
        "حداکثر: <code>168</code> ساعت\n\n"
        "مثلاً برای اجرای هر ۱۲ ساعت: <code>12</code>"
    )
    await state.update_data(
        prompt_message_id=prompt.message_id,
        prompt_chat_id=prompt.chat.id,
    )


@router.message(
    TestAccountSettingsStates.waiting_cleanup_interval_hours,
    IsAdmin(),
)
async def save_cleanup_interval(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    try:
        value = int((message.text or "").strip())

        if value < 1 or value > 168:
            raise ValueError

    except ValueError:
        await message.answer(
            "❌ مقدار نامعتبر است. "
            "یک عدد صحیح بین ۱ تا ۱۶۸ ساعت وارد کنید."
        )
        return

    state_data = await state.get_data()
    prompt_message_id = state_data.get("prompt_message_id")
    prompt_chat_id = state_data.get("prompt_chat_id")

    settings = await TestAccountSettings.get_or_create(session)
    settings.cleanup_interval_hours = value

    await session.commit()

    reschedule_cleanup(value)

    await state.clear()

    confirmation = await message.answer(
        f"✅ فاصله پاکسازی خودکار روی هر "
        f"<b>{value} ساعت</b> تنظیم شد.",
        reply_markup=_keyboard(settings),
    )

    if prompt_message_id and prompt_chat_id:
        _schedule_delete(
            message.bot,
            prompt_chat_id,
            prompt_message_id,
            5.0,
        )

    _schedule_delete(
        message.bot,
        confirmation.chat.id,
        confirmation.message_id,
        5.0,
    )


@router.callback_query(
    F.data == "test_account_settings:reuse_after_days",
    IsAdmin(),
)
async def edit_reuse_after_days(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(TestAccountSettingsStates.waiting_reuse_after_days)
    await callback.answer()
    prompt = await callback.message.answer(
        "♻️ <b>فاصله استفاده مجدد از اکانت تست</b>\n\n"
        "تعداد روز از آخرین تست را وارد کنید.\n"
        "عدد <code>0</code> یعنی هر کاربر فقط یک بار مجاز باشد.\n"
        "مثلاً: <code>30</code>"
    )
    await state.update_data(
        prompt_message_id=prompt.message_id,
        prompt_chat_id=prompt.chat.id,
    )


@router.message(
    TestAccountSettingsStates.waiting_reuse_after_days,
    IsAdmin(),
)
async def save_reuse_after_days(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    try:
        value = int((message.text or "").strip())
        if value < 0 or value > 3650:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ مقدار نامعتبر است. عددی بین ۰ تا ۳۶۵۰ روز وارد کنید."
        )
        return

    state_data = await state.get_data()
    settings = await TestAccountSettings.get_or_create(session)
    settings.reuse_after_days = value
    await session.commit()
    await state.clear()

    text = (
        "✅ فاصله استفاده مجدد ذخیره شد.\n"
        f"از این پس فاصله مجاز: <b>{value} روز</b>"
        if value
        else
        "✅ حالت یک‌بارمصرف فعال شد."
    )
    confirmation = await message.answer(
        text,
        reply_markup=_keyboard(settings),
    )

    prompt_message_id = state_data.get("prompt_message_id")
    prompt_chat_id = state_data.get("prompt_chat_id")
    if prompt_message_id and prompt_chat_id:
        _schedule_delete(message.bot, prompt_chat_id, prompt_message_id, 5.0)
    _schedule_delete(
        message.bot,
        confirmation.chat.id,
        confirmation.message_id,
        5.0,
    )


@router.callback_query(
    F.data == "test_account_settings:reset_all",
    IsAdmin(),
)
async def reset_all_test_account_users(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    settings = await TestAccountSettings.get_or_create(session)
    settings.reset_at = datetime.utcnow()
    await session.commit()
    await callback.answer("ریست سراسری انجام شد.", show_alert=True)
    await _render(callback, session)


@router.callback_query(
    F.data == "test_account_settings:reset_user",
    IsAdmin(),
)
async def reset_one_test_account_user(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(TestAccountSettingsStates.waiting_reset_user_id)
    await callback.answer()
    prompt = await callback.message.answer(
        "👤 <b>ریست استفاده یک کاربر</b>\n\n"
        "Telegram ID کاربر را وارد کنید.\n"
        "مثلاً: <code>78797797</code>"
    )
    await state.update_data(
        prompt_message_id=prompt.message_id,
        prompt_chat_id=prompt.chat.id,
    )


@router.message(
    TestAccountSettingsStates.waiting_reset_user_id,
    IsAdmin(),
)
async def save_reset_one_test_account_user(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    try:
        tg_id = int((message.text or "").strip())
        if tg_id <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Telegram ID نامعتبر است.")
        return

    user = await User.get(session=session, tg_id=tg_id)
    if user is None:
        await message.answer("❌ کاربر پیدا نشد.")
        return

    user.trial_reset_at = datetime.utcnow()
    await session.commit()
    await state.clear()

    confirmation = await message.answer(
        f"✅ امکان استفاده مجدد برای کاربر <code>{tg_id}</code> ریست شد.",
        reply_markup=await _keyboard_after_refresh(session),
    )

    state_data = await state.get_data()
    prompt_message_id = state_data.get("prompt_message_id")
    prompt_chat_id = state_data.get("prompt_chat_id")
    if prompt_message_id and prompt_chat_id:
        _schedule_delete(message.bot, prompt_chat_id, prompt_message_id, 5.0)
    _schedule_delete(
        message.bot,
        confirmation.chat.id,
        confirmation.message_id,
        5.0,
    )


async def _keyboard_after_refresh(
    session: AsyncSession,
) -> InlineKeyboardMarkup:
    settings = await TestAccountSettings.get_or_create(session)
    return _keyboard(settings)


@router.callback_query(
    F.data == "test_account_settings:cleanup",
    IsAdmin(),
)
async def run_test_cleanup(
    callback: CallbackQuery,
    services: ServicesContainer,
) -> None:
    await callback.answer(
        "پاکسازی شروع شد...",
        show_alert=False,
    )

    removed = await services.test_account.cleanup_expired()

    result_message = await callback.message.answer(
        f"🧹 پاکسازی انجام شد. تعداد اکانت‌های حذف‌شده "
        f"از 3X-UI: <b>{removed}</b>"
    )
    _schedule_delete(
        callback.bot,
        result_message.chat.id,
        result_message.message_id,
        5.0,
    )
