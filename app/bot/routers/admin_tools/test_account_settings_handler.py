import asyncio

from aiogram import F, Router
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
from app.db.models import TestAccount, TestAccountSettings

router = Router(name=__name__)


async def _delete_message_after(message: Message, delay: float = 5.0) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        # The message may already have been deleted or become unavailable.
        pass


def _schedule_delete(message: Message, delay: float = 5.0) -> None:
    asyncio.create_task(_delete_message_after(message, delay))


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
                    text="🕐 تغییر فاصله پاکسازی",
                    callback_data="test_account_settings:cleanup_interval",
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

    text = (
        "🎁 <b>مدیریت اکانت تست</b>\n\n"
        f"وضعیت: {status}\n"
        f"حجم هر تست: <b>{settings.volume_mb} MB</b>\n"
        f"مدت هر تست: <b>{settings.duration_days} روز</b>\n"
        f"پاکسازی خودکار: <b>هر {settings.cleanup_interval_hours} ساعت</b>\n\n"
        f"تعداد تست‌های ثبت‌شده: <b>{total_used}</b>\n"
        f"تست‌های فعال فعلی: <b>{active}</b>\n\n"
        "هر کاربر فقط یک بار می‌تواند اکانت تست دریافت کند و "
        "سابقه آن حتی پس از حذف Client از 3X-UI حفظ می‌شود."
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

    await callback.message.edit_text(
        "📦 <b>حجم اکانت تست</b>\n\n"
        "حجم جدید را بر حسب MB وارد کنید.\n"
        "مثلاً: <code>200</code>"
    )
    await state.update_data(prompt_message_id=callback.message.message_id)


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

    settings = await TestAccountSettings.get_or_create(session)
    settings.volume_mb = value

    await session.commit()
    await state.clear()

    confirmation = await message.answer(
        "✅ حجم اکانت تست ذخیره شد.",
        reply_markup=_keyboard(settings),
    )

    if prompt_message_id:
        _schedule_delete(
            message.bot.session,
            5.0,
        )

    _schedule_delete(confirmation, 5.0)


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

    await callback.message.edit_text(
        "⏱ <b>مدت اکانت تست</b>\n\n"
        "مدت جدید را بر حسب روز وارد کنید.\n"
        "مثلاً: <code>2</code>"
    )
    await state.update_data(prompt_message_id=callback.message.message_id)


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

    settings = await TestAccountSettings.get_or_create(session)
    settings.duration_days = value

    await session.commit()
    await state.clear()

    confirmation = await message.answer(
        "✅ مدت اکانت تست ذخیره شد.",
        reply_markup=_keyboard(settings),
    )

    if prompt_message_id:
        _schedule_delete(
            message.bot.session,
            5.0,
        )

    _schedule_delete(confirmation, 5.0)


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

    await callback.message.edit_text(
        "🕐 <b>فاصله پاکسازی خودکار</b>\n\n"
        "فاصله اجرای پاکسازی را بر حسب ساعت وارد کنید.\n"
        "حداقل: <code>1</code> ساعت\n"
        "حداکثر: <code>168</code> ساعت\n\n"
        "مثلاً برای اجرای هر ۱۲ ساعت: <code>12</code>"
    )
    await state.update_data(prompt_message_id=callback.message.message_id)


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

    if prompt_message_id:
        _schedule_delete(
            message.bot.session,
            5.0,
        )

    _schedule_delete(confirmation, 5.0)


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
    _schedule_delete(result_message, 5.0)
