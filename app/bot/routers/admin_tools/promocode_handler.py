import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.misc.keyboard import back_keyboard
from app.bot.routers.admin_tools.gift_promocode_handler import gift_menu_keyboard
from app.bot.routers.admin_tools.keyboard import promocode_duration_keyboard
from app.bot.utils.constants import INPUT_PROMOCODE_KEY, MAIN_MESSAGE_ID_KEY
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Promocode, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class CreatePromocodeStates(StatesGroup):
    selecting_volume = State()
    selecting_duration = State()
    entering_validity = State()


class DeletePromocodeStates(StatesGroup):
    promocode_input = State()


class EditPromocodeStates(StatesGroup):
    promocode_input = State()
    entering_volume = State()
    selecting_duration = State()
    entering_validity = State()


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


def _summary(volume_gb: int, duration: int, validity: int, expires_at: datetime | None) -> str:
    expiry = "بدون انقضا" if expires_at is None else format_jalali(expires_at)
    return (
        f"📦 حجم سرویس: <b>{volume_gb} GB</b>\n"
        f"⏱ مدت سرویس: <b>{duration} روز</b>\n"
        f"👤 کاربر: <b>1</b>\n"
        f"⌛ اعتبار کد: <b>{_validity_label(validity)}</b>\n"
        f"📅 انقضای کد: <b>{expiry}</b>"
    )


async def show_promocode_editor_main(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    await message.bot.edit_message_text(
        text=_("promocode_editor:message:main"),
        chat_id=message.chat.id,
        message_id=main_message_id,
        reply_markup=gift_menu_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.PROMOCODE_EDITOR, IsAdmin())
async def callback_promocode_editor(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} opened promocode editor.")
    await show_promocode_editor_main(message=callback.message, state=state)


@router.callback_query(F.data == NavAdminTools.CREATE_PROMOCODE, IsAdmin())
async def callback_create_promocode(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} started creating gift promocode.")
    await state.set_state(CreatePromocodeStates.selecting_volume)
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>ساخت کد هدیه</b>\n\n"
        "ابتدا حجم سرویس هدیه را به گیگابایت وارد کنید.\n"
        "مثال: <code>30</code>\n\n"
        "👤 سرویس هدیه با ۱ کاربر ساخته می‌شود.",
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(CreatePromocodeStates.selecting_volume, IsAdmin())
async def callback_volume_entered(message: Message, state: FSMContext) -> None:
    volume = _parse_positive_int(message.text)
    if volume is None:
        await message.answer("❌ حجم نامعتبر است. یک عدد صحیح بزرگ‌تر از صفر وارد کنید؛ مثلاً <code>30</code>.")
        return
    await state.update_data(gift_volume_gb=volume)
    await state.set_state(CreatePromocodeStates.selecting_duration)
    await message.answer("⏱ <b>مدت سرویس هدیه</b> را انتخاب کنید:", reply_markup=promocode_duration_keyboard())


@router.callback_query(CreatePromocodeStates.selecting_duration, IsAdmin())
async def callback_duration_selected(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    duration = int(callback.data)
    await state.update_data(gift_duration_days=duration)
    await state.set_state(CreatePromocodeStates.entering_validity)
    await callback.answer()
    await callback.message.edit_text(
        "⌛ <b>مدت اعتبار خود کد هدیه</b> را به روز وارد کنید.\n\n"
        "این مدت از لحظه ساخت کد محاسبه می‌شود.\n"
        "مثلاً <code>10</code> یعنی کد تا ۱۰ روز قابل استفاده است.\n"
        "برای کد بدون انقضا، <code>0</code> وارد کنید.",
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(CreatePromocodeStates.entering_validity, IsAdmin())
async def callback_validity_entered(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    validity = _parse_validity(message.text)
    if validity is None:
        await message.answer("❌ مدت اعتبار نامعتبر است. عدد صفر یا یک عدد صحیح مثبت وارد کنید؛ مثلاً <code>10</code>.")
        return

    data = await state.get_data()
    volume = int(data["gift_volume_gb"])
    duration = int(data["gift_duration_days"])
    expires_at = _expires_at(validity)
    promocode = await Promocode.create(
        session=session,
        duration=duration,
        volume_gb=volume,
        is_gift=True,
        expires_at=expires_at,
    )
    await show_promocode_editor_main(message=message, state=state)

    if promocode:
        await services.notification.notify_by_message(
            message=message,
            text=(
                "🎁 <b>کد هدیه ساخته شد</b>\n\n"
                f"🔑 کد: <code>{promocode.code}</code>\n"
                f"{_summary(volume, duration, validity, expires_at)}\n\n"
                "مشتری کد را از مسیر <b>کیف پول → کد هدیه</b> وارد می‌کند."
            ),
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:create_failed"),
            duration=5,
        )


@router.callback_query(F.data == NavAdminTools.DELETE_PROMOCODE, IsAdmin())
async def callback_delete_promocode(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} started deleting promocode.")
    await state.set_state(DeletePromocodeStates.promocode_input)
    await callback.answer()
    await callback.message.edit_text(
        text=_("promocode_editor:message:delete"),
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(DeletePromocodeStates.promocode_input, IsAdmin())
async def handle_promocode_input(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    input_promocode = (message.text or "").strip().upper()
    logger.info(f"Admin {user.tg_id} entered promocode: {input_promocode} for deleting.")

    if await Promocode.delete(session=session, code=input_promocode):
        await show_promocode_editor_main(message=message, state=state)
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:deleted_success").format(promocode=input_promocode),
            duration=5,
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:delete_failed"),
            duration=5,
        )


@router.callback_query(F.data == NavAdminTools.EDIT_PROMOCODE, IsAdmin())
async def callback_edit_promocode(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    logger.info(f"Admin {user.tg_id} started editing promocode.")
    await state.set_state(EditPromocodeStates.promocode_input)
    await callback.answer()
    await callback.message.edit_text(
        text=_("promocode_editor:message:edit"),
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(EditPromocodeStates.promocode_input, IsAdmin())
async def handle_promocode_edit_input(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    input_promocode = (message.text or "").strip().upper()
    promocode = await Promocode.get(session=session, code=input_promocode)
    if promocode and not promocode.is_activated and not promocode.is_expired:
        await state.update_data({INPUT_PROMOCODE_KEY: input_promocode})
        await state.set_state(EditPromocodeStates.entering_volume)
        expiry = "بدون انقضا" if promocode.expires_at is None else format_jalali(promocode.expires_at)
        await message.answer(
            "🎁 <b>ویرایش کد هدیه</b>\n\n"
            f"کد: <code>{promocode.code}</code>\n"
            f"حجم فعلی: <b>{promocode.volume_gb} GB</b>\n"
            f"مدت فعلی: <b>{promocode.duration} روز</b>\n"
            f"انقضای کد: <b>{expiry}</b>\n\n"
            "📦 حجم جدید را به گیگابایت وارد کنید:",
            reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:edit_failed"),
            duration=5,
        )


@router.message(EditPromocodeStates.entering_volume, IsAdmin())
async def edit_volume_entered(message: Message, state: FSMContext) -> None:
    volume = _parse_positive_int(message.text)
    if volume is None:
        await message.answer("❌ حجم نامعتبر است. یک عدد صحیح بزرگ‌تر از صفر وارد کنید.")
        return
    await state.update_data(gift_volume_gb=volume)
    await state.set_state(EditPromocodeStates.selecting_duration)
    await message.answer("⏱ <b>مدت جدید سرویس</b> را انتخاب کنید:", reply_markup=promocode_duration_keyboard())


@router.callback_query(EditPromocodeStates.selecting_duration, IsAdmin())
async def edit_duration_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(gift_duration_days=int(callback.data))
    await state.set_state(EditPromocodeStates.entering_validity)
    await callback.answer()
    await callback.message.edit_text(
        "⌛ <b>مدت اعتبار جدید کد</b> را به روز وارد کنید.\n\n"
        "از زمان ثبت این ویرایش محاسبه می‌شود.\n"
        "<code>0</code> = بدون انقضا",
        reply_markup=back_keyboard(NavAdminTools.PROMOCODE_EDITOR),
    )


@router.message(EditPromocodeStates.entering_validity, IsAdmin())
async def edit_validity_entered(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    validity = _parse_validity(message.text)
    if validity is None:
        await message.answer("❌ مدت اعتبار نامعتبر است. عدد صفر یا یک عدد صحیح مثبت وارد کنید.")
        return

    code = await state.get_value(INPUT_PROMOCODE_KEY)
    data = await state.get_data()
    volume = int(data["gift_volume_gb"])
    duration = int(data["gift_duration_days"])
    expires_at = _expires_at(validity)
    promocode = await Promocode.update(
        session=session,
        code=code,
        volume_gb=volume,
        duration=duration,
        expires_at=expires_at,
        is_gift=True,
    )
    await show_promocode_editor_main(message=message, state=state)
    if promocode:
        await services.notification.notify_by_message(
            message=message,
            text=(
                "✅ <b>کد هدیه ویرایش شد.</b>\n\n"
                f"🔑 کد: <code>{code}</code>\n"
                f"{_summary(volume, duration, validity, expires_at)}"
            ),
        )
    else:
        await services.notification.notify_by_message(
            message=message,
            text=_("promocode_editor:ntf:edit_failed"),
            duration=5,
        )
