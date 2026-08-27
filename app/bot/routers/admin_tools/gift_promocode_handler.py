from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.admin_tools.keyboard import promocode_duration_keyboard
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavAdminTools
from app.bot.utils.validation import is_valid_user_id
from app.db.models import Promocode, User

router = Router(name=__name__)


class GiftPromocodeStates(StatesGroup):
    user_id = State()
    user_volume = State()
    user_duration = State()
    user_validity = State()
    all_volume = State()
    all_duration = State()
    all_validity = State()


def gift_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 ساخت و ارسال کد هدیه برای مشتری", callback_data=NavAdminTools.CREATE_AND_SEND_PROMOCODE_USER)],
            [InlineKeyboardButton(text="🎁📢 ساخت و ارسال کد هدیه برای همه مشتریان", callback_data=NavAdminTools.CREATE_AND_SEND_PROMOCODE_ALL)],
            [InlineKeyboardButton(text="➕ ساخت کد هدیه بدون ارسال", callback_data=NavAdminTools.CREATE_PROMOCODE)],
            [InlineKeyboardButton(text="🗑 حذف کد هدیه", callback_data=NavAdminTools.DELETE_PROMOCODE)],
            [InlineKeyboardButton(text="✏️ ویرایش کد هدیه", callback_data=NavAdminTools.EDIT_PROMOCODE)],
            [InlineKeyboardButton(text="📊 گزارشات", callback_data=NavAdminTools.GIFT_REPORTS)],
            [back_to_main_menu_button()],
        ]
    )


def _duration_keyboard() -> InlineKeyboardMarkup:
    return promocode_duration_keyboard()


def _config_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back_button(NavAdminTools.PROMOCODE_EDITOR)]])


def _parse_positive_int(text: str | None) -> int | None:
    try:
        value = int((text or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_validity(text: str | None) -> int | None:
    try:
        value = int((text or "").strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def _expires_at(validity_days: int) -> datetime | None:
    if validity_days == 0:
        return None
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=validity_days)


def _validity_label(validity_days: int) -> str:
    return "بدون انقضا" if validity_days == 0 else f"{validity_days} روز"


def _gift_summary(volume_gb: int, duration_days: int, validity_days: int) -> str:
    return (
        f"📦 حجم سرویس: <b>{volume_gb} GB</b>\n"
        f"⏱ مدت سرویس: <b>{duration_days} روز</b>\n"
        f"👤 کاربر: <b>1</b>\n"
        f"⌛ اعتبار کد: <b>{_validity_label(validity_days)}</b>"
    )


@router.callback_query(F.data == NavAdminTools.PROMOCODE_EDITOR, IsAdmin())
async def gift_promocode_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>مدیریت کدهای هدیه</b>\n\n"
        "در این بخش می‌توانید برای هر کد، مشخصات سرویس و مدت اعتبار خود کد را تعیین کنید.\n\n"
        "📦 حجم سرویس\n"
        "⏱ مدت سرویس\n"
        "⌛ مدت اعتبار کد از زمان ساخت\n\n"
        "پس از مصرف کد، یک سرویس VPN واقعی ساخته و در «سرویس‌های من» ثبت می‌شود؛ سرویس هدیه قابلیت تمدید ندارد.",
        reply_markup=gift_menu_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.CREATE_AND_SEND_PROMOCODE_USER, IsAdmin())
async def gift_to_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiftPromocodeStates.user_id)
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>ارسال کد هدیه به یک مشتری</b>\n\n"
        "Telegram ID مشتری را ارسال کنید یا پیام او را برای ربات فوروارد کنید.",
        reply_markup=_config_back_keyboard(),
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
    await state.set_state(GiftPromocodeStates.user_volume)
    await message.answer(
        f"👤 مشتری: <b>{user.first_name}</b>\n🆔 <code>{raw_id}</code>\n\n"
        "📦 <b>حجم سرویس هدیه</b> را به گیگابایت ارسال کنید.\n"
        "مثال: <code>30</code>",
        reply_markup=_config_back_keyboard(),
    )


@router.message(GiftPromocodeStates.user_volume, IsAdmin())
async def gift_to_user_volume(message: Message, state: FSMContext) -> None:
    volume = _parse_positive_int(message.text)
    if volume is None:
        await message.answer("❌ حجم نامعتبر است. یک عدد صحیح بزرگ‌تر از صفر وارد کنید؛ مثلاً <code>30</code>.")
        return
    await state.update_data(gift_volume_gb=volume)
    await state.set_state(GiftPromocodeStates.user_duration)
    await message.answer("⏱ <b>مدت سرویس هدیه</b> را انتخاب کنید:", reply_markup=_duration_keyboard())


@router.callback_query(GiftPromocodeStates.user_duration, IsAdmin())
async def gift_to_user_duration(callback: CallbackQuery, state: FSMContext) -> None:
    duration = int(callback.data)
    await state.update_data(gift_duration_days=duration)
    await state.set_state(GiftPromocodeStates.user_validity)
    await callback.answer()
    await callback.message.edit_text(
        "⌛ <b>مدت اعتبار خود کد هدیه</b> را به روز ارسال کنید.\n\n"
        "این مدت از لحظه ساخت کد محاسبه می‌شود.\n"
        "مثلاً <code>10</code> یعنی کد تا ۱۰ روز قابل استفاده است.\n"
        "برای کد بدون انقضا، <code>0</code> وارد کنید.",
        reply_markup=_config_back_keyboard(),
    )


@router.message(GiftPromocodeStates.user_validity, IsAdmin())
async def gift_to_user_create(message: Message, session: AsyncSession, state: FSMContext, services: ServicesContainer) -> None:
    validity = _parse_validity(message.text)
    if validity is None:
        await message.answer("❌ مدت اعتبار نامعتبر است. عدد صفر یا یک عدد صحیح مثبت وارد کنید؛ مثلاً <code>10</code>.")
        return

    data = await state.get_data()
    user_id = int(data["gift_user_id"])
    volume_gb = int(data["gift_volume_gb"])
    duration = int(data["gift_duration_days"])
    user = await User.get(session=session, tg_id=user_id)
    if not user:
        await state.clear()
        await message.answer("❌ مشتری دیگر وجود ندارد.", reply_markup=gift_menu_keyboard())
        return

    promocode = await Promocode.create(session=session, duration=duration, volume_gb=volume_gb, is_gift=True, recipient_tg_id=user_id, expires_at=_expires_at(validity))
    if not promocode:
        await state.clear()
        await message.answer("❌ ساخت کد هدیه ناموفق بود.", reply_markup=gift_menu_keyboard())
        return

    expiry_text = "بدون انقضا" if promocode.expires_at is None else format_jalali(promocode.expires_at)
    text = (
        "🎁 <b>کد هدیه برای شما</b>\n\n"
        f"🔑 کد: <code>{promocode.code}</code>\n"
        f"{_gift_summary(volume_gb, duration, validity)}\n"
        f"📅 انقضای کد: <b>{expiry_text}</b>\n\n"
        "کد را از مسیر <b>کیف پول → کد هدیه</b> وارد کنید تا کانفیگ هدیه برایتان ساخته شود."
    )
    sent = await services.notification.notify_by_id(chat_id=user_id, text=text)

    await state.clear()
    if sent:
        await message.answer(
            "✅ <b>کد هدیه ساخته و با موفقیت برای مشتری ارسال شد.</b>\n\n"
            f"👤 <b>{user.first_name}</b>\n"
            f"🆔 <code>{user_id}</code>\n"
            f"🔑 کد: <code>{promocode.code}</code>\n"
            f"{_gift_summary(volume_gb, duration, validity)}\n"
            f"📅 انقضای کد: <b>{expiry_text}</b>",
            reply_markup=gift_menu_keyboard(),
        )
    else:
        await Promocode.delete(session=session, code=promocode.code)
        await message.answer("❌ ارسال پیام به مشتری ناموفق بود؛ کد هدیه نیز حذف شد.", reply_markup=gift_menu_keyboard())


@router.callback_query(F.data == NavAdminTools.CREATE_AND_SEND_PROMOCODE_ALL, IsAdmin())
async def gift_to_all_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiftPromocodeStates.all_volume)
    await callback.answer()
    await callback.message.edit_text("🎁📢 <b>ارسال کد هدیه برای همه مشتریان</b>\n\n📦 حجم سرویس هدیه را به گیگابایت ارسال کنید.\nمثال: <code>30</code>", reply_markup=_config_back_keyboard())


@router.message(GiftPromocodeStates.all_volume, IsAdmin())
async def gift_to_all_volume(message: Message, state: FSMContext) -> None:
    volume = _parse_positive_int(message.text)
    if volume is None:
        await message.answer("❌ حجم نامعتبر است. یک عدد صحیح بزرگ‌تر از صفر وارد کنید؛ مثلاً <code>30</code>.")
        return
    await state.update_data(gift_volume_gb=volume)
    await state.set_state(GiftPromocodeStates.all_duration)
    await message.answer("⏱ <b>مدت سرویس هدیه</b> را انتخاب کنید:", reply_markup=_duration_keyboard())


@router.callback_query(GiftPromocodeStates.all_duration, IsAdmin())
async def gift_to_all_duration(callback: CallbackQuery, state: FSMContext) -> None:
    duration = int(callback.data)
    await state.update_data(gift_duration_days=duration)
    await state.set_state(GiftPromocodeStates.all_validity)
    await callback.answer()
    await callback.message.edit_text("⌛ <b>مدت اعتبار کدها</b> را به روز ارسال کنید.\n\nاین مدت از زمان ساخت هر کد محاسبه می‌شود.\nمثلاً <code>10</code> یعنی هر کد تا ۱۰ روز قابل استفاده است.\nبرای بدون انقضا، <code>0</code> وارد کنید.", reply_markup=_config_back_keyboard())


@router.message(GiftPromocodeStates.all_validity, IsAdmin())
async def gift_to_all_create(message: Message, session: AsyncSession, state: FSMContext, services: ServicesContainer) -> None:
    validity = _parse_validity(message.text)
    if validity is None:
        await message.answer("❌ مدت اعتبار نامعتبر است. عدد صفر یا یک عدد صحیح مثبت وارد کنید؛ مثلاً <code>10</code>.")
        return

    data = await state.get_data()
    volume_gb = int(data["gift_volume_gb"])
    duration = int(data["gift_duration_days"])
    users = await User.get_all(session=session)
    await message.answer(f"⏳ در حال ساخت و ارسال {len(users)} کد هدیه...")

    success = 0
    failed = 0
    for user in users:
        promocode = await Promocode.create(session=session, duration=duration, volume_gb=volume_gb, is_gift=True, recipient_tg_id=user.tg_id, expires_at=_expires_at(validity))
        if not promocode:
            failed += 1
            continue

        expiry_text = "بدون انقضا" if promocode.expires_at is None else format_jalali(promocode.expires_at)
        text = (
            "🎁 <b>کد هدیه ویژه شما</b>\n\n"
            f"🔑 کد: <code>{promocode.code}</code>\n"
            f"{_gift_summary(volume_gb, duration, validity)}\n"
            f"📅 انقضای کد: <b>{expiry_text}</b>\n\n"
            "کد را از مسیر <b>کیف پول → کد هدیه</b> وارد کنید تا کانفیگ هدیه برایتان ساخته شود."
        )
        sent = await services.notification.notify_by_id(chat_id=user.tg_id, text=text)
        if sent:
            success += 1
        else:
            failed += 1
            await Promocode.delete(session=session, code=promocode.code)

    await state.clear()
    await message.answer(
        "✅ <b>ارسال کدهای هدیه تمام شد.</b>\n\n"
        f"👥 کل مشتریان: <b>{len(users)}</b>\n"
        f"✅ ارسال موفق: <b>{success}</b>\n"
        f"❌ ناموفق: <b>{failed}</b>\n\n"
        f"{_gift_summary(volume_gb, duration, validity)}",
        reply_markup=gift_menu_keyboard(),
    )
