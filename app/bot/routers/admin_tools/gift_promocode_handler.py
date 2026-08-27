import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.routers.admin_tools.keyboard import promocode_duration_keyboard
from app.bot.utils.navigation import NavAdminTools
from app.bot.utils.validation import is_valid_user_id
from app.db.models import Promocode, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class GiftPromocodeStates(StatesGroup):
    user_id = State()
    user_duration = State()
    all_duration = State()


def gift_menu_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 ساخت و ارسال کد هدیه برای مشتری", callback_data=NavAdminTools.CREATE_AND_SEND_PROMOCODE_USER)],
            [InlineKeyboardButton(text="🎁📢 ساخت و ارسال کد هدیه برای همه مشتریان", callback_data=NavAdminTools.CREATE_AND_SEND_PROMOCODE_ALL)],
            [InlineKeyboardButton(text="➕ ساخت کد هدیه بدون ارسال", callback_data=NavAdminTools.CREATE_PROMOCODE)],
            [InlineKeyboardButton(text="🗑 حذف کد هدیه", callback_data=NavAdminTools.DELETE_PROMOCODE)],
            [InlineKeyboardButton(text="✏️ ویرایش کد هدیه", callback_data=NavAdminTools.EDIT_PROMOCODE)],
            [back_to_main_menu_button()],
        ]
    )


def _duration_keyboard():
    return promocode_duration_keyboard()


@router.callback_query(F.data == NavAdminTools.PROMOCODE_EDITOR, IsAdmin())
async def gift_promocode_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>مدیریت کدهای هدیه</b>\n\n"
        "از این بخش می‌توانید کد هدیه بسازید و مستقیماً برای یک مشتری یا همه مشتریان ارسال کنید.\n\n"
        "⚠️ در ارسال گروهی برای هر مشتری یک کد یکتای جداگانه ساخته می‌شود؛ بنابراین یک کد بین چند مشتری مشترک نخواهد بود.",
        reply_markup=gift_menu_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.CREATE_AND_SEND_PROMOCODE_USER, IsAdmin())
async def gift_to_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiftPromocodeStates.user_id)
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>ارسال کد هدیه به یک مشتری</b>\n\n"
        "Telegram ID مشتری را ارسال کنید یا پیام او را برای ربات فوروارد کنید.",
        reply_markup=back_button(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(GiftPromocodeStates.user_id, IsAdmin())
async def gift_to_user_id(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw_id = str(message.forward_from.id) if message.forward_from else (message.text or "").strip()
    if not is_valid_user_id(raw_id):
        await message.answer("❌ Telegram ID نامعتبر است.")
        return

    user = await User.get(session=session, tg_id=int(raw_id))
    if not user:
        await message.answer("❌ این مشتری در دیتابیس پیدا نشد.")
        return

    await state.update_data(gift_user_id=int(raw_id))
    await state.set_state(GiftPromocodeStates.user_duration)
    await message.answer(
        f"👤 مشتری: <b>{user.first_name}</b>\n"
        f"🆔 <code>{raw_id}</code>\n\n"
        "مدت کد هدیه را انتخاب کنید:",
        reply_markup=_duration_keyboard(),
    )


@router.callback_query(GiftPromocodeStates.user_duration, IsAdmin())
async def gift_to_user_create(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    duration = int(callback.data)
    data = await state.get_data()
    user_id = int(data["gift_user_id"])
    user = await User.get(session=session, tg_id=user_id)

    if not user:
        await state.clear()
        await callback.message.edit_text("❌ مشتری دیگر وجود ندارد.", reply_markup=gift_menu_keyboard())
        return

    promocode = await Promocode.create(session=session, duration=duration)
    if not promocode:
        await state.clear()
        await callback.message.edit_text("❌ ساخت کد هدیه ناموفق بود.", reply_markup=gift_menu_keyboard())
        return

    text = (
        "🎁 <b>کد هدیه برای شما</b>\n\n"
        f"🔑 کد: <code>{promocode.code}</code>\n"
        f"⏱ مدت هدیه: <b>{duration} روز</b>\n\n"
        "کد را در بخش خرید سرویس وارد کنید."
    )
    sent = await services.notification.notify_by_id(chat_id=user_id, text=text)

    await state.clear()
    if sent:
        await callback.message.edit_text(
            "✅ کد هدیه ساخته و با موفقیت برای مشتری ارسال شد.\n\n"
            f"👤 <b>{user.first_name}</b>\n"
            f"🆔 <code>{user_id}</code>\n"
            f"🔑 کد: <code>{promocode.code}</code>\n"
            f"⏱ مدت: <b>{duration} روز</b>",
            reply_markup=gift_menu_keyboard(),
        )
    else:
        await Promocode.delete(session=session, code=promocode.code)
        await callback.message.edit_text(
            "❌ ارسال پیام به مشتری ناموفق بود؛ کد هدیه نیز حذف شد تا کد بلااستفاده در دیتابیس باقی نماند.",
            reply_markup=gift_menu_keyboard(),
        )


@router.callback_query(F.data == NavAdminTools.CREATE_AND_SEND_PROMOCODE_ALL, IsAdmin())
async def gift_to_all_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiftPromocodeStates.all_duration)
    await callback.answer()
    await callback.message.edit_text(
        "🎁📢 <b>ارسال کد هدیه برای همه مشتریان</b>\n\n"
        "مدت کد هدیه را انتخاب کنید. برای هر مشتری یک کد کاملاً مستقل ساخته می‌شود:",
        reply_markup=_duration_keyboard(),
    )


@router.callback_query(GiftPromocodeStates.all_duration, IsAdmin())
async def gift_to_all_create(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    duration = int(callback.data)
    users = await User.get_all(session=session)
    await callback.message.edit_text(f"⏳ در حال ساخت و ارسال {len(users)} کد هدیه...")

    success = 0
    failed = 0
    created_codes: list[str] = []

    for user in users:
        promocode = await Promocode.create(session=session, duration=duration)
        if not promocode:
            failed += 1
            continue

        text = (
            "🎁 <b>کد هدیه ویژه شما</b>\n\n"
            f"🔑 کد: <code>{promocode.code}</code>\n"
            f"⏱ مدت هدیه: <b>{duration} روز</b>\n\n"
            "کد را در بخش خرید سرویس وارد کنید."
        )
        sent = await services.notification.notify_by_id(chat_id=user.tg_id, text=text)
        if sent:
            success += 1
            created_codes.append(promocode.code)
        else:
            failed += 1
            await Promocode.delete(session=session, code=promocode.code)

    await state.clear()
    await callback.message.edit_text(
        "✅ <b>ارسال کدهای هدیه تمام شد.</b>\n\n"
        f"👥 کل مشتریان: <b>{len(users)}</b>\n"
        f"✅ ارسال موفق: <b>{success}</b>\n"
        f"❌ ناموفق: <b>{failed}</b>\n"
        f"⏱ مدت: <b>{duration} روز</b>\n\n"
        "برای هر ارسال موفق، کد جداگانه ساخته شده است.",
        reply_markup=gift_menu_keyboard(),
    )
