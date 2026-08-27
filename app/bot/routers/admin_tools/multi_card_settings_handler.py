from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.config import Config
from app.db.models import CardSettings

router = Router(name=__name__)


class MultiCardSettingsState(StatesGroup):
    waiting_card_number = State()
    waiting_bank_name = State()
    waiting_holder_name = State()


def _card_label(card: CardSettings, index: int) -> str:
    status = "🟢" if card.is_active else "🔴"
    bank = f" — {card.bank_name}" if card.bank_name else ""
    holder = f" — {card.card_holder_name}" if card.card_holder_name else ""
    return f"{index}. {status} {card.card_number}{bank}{holder}"


def menu_markup(cards: list[CardSettings]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, card in enumerate(cards, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_card_label(card, index),
                    callback_data=f"cardsettings:view:{card.id}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ افزودن کارت جدید", callback_data="cardsettings:add")]
    )
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def detail_markup(card: CardSettings) -> InlineKeyboardMarkup:
    status_callback = "cardsettings:disable" if card.is_active else "cardsettings:enable"
    status_text = "🔴 غیرفعال کردن کارت" if card.is_active else "🟢 فعال کردن کارت"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش کارت", callback_data=f"cardsettings:edit:{card.id}")],
            [InlineKeyboardButton(text=status_text, callback_data=f"{status_callback}:{card.id}")],
            [InlineKeyboardButton(text="🗑 حذف کارت", callback_data=f"cardsettings:delete:{card.id}")],
            [InlineKeyboardButton(text="🔙 لیست کارت‌ها", callback_data=NavAdminTools.CARD_SETTINGS)],
        ]
    )


async def _show_menu(target: CallbackQuery | Message, session: AsyncSession) -> None:
    cards = await CardSettings.get_all(session)
    if cards:
        text = (
            "💳 <b>مدیریت کارت به کارت</b>\n\n"
            "کارت‌ها به همین ترتیب در چرخه تعویض کارت استفاده می‌شوند:\n\n"
            + "\n".join(_card_label(card, i) for i, card in enumerate(cards, start=1))
            + "\n\n➕ کارت جدید همیشه در انتهای این ترتیب اضافه می‌شود."
        )
    else:
        text = (
            "💳 <b>مدیریت کارت به کارت</b>\n\n"
            "هنوز هیچ کارت فعالی ثبت نشده است.\n"
            "برای شروع، کارت اول را اضافه کنید."
        )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=menu_markup(cards))
    else:
        await target.answer(text, reply_markup=menu_markup(cards))


async def _get_card(session: AsyncSession, card_id: int) -> CardSettings | None:
    return await session.get(CardSettings, card_id)


@router.callback_query(F.data == NavAdminTools.CARD_SETTINGS, IsAdmin())
async def card_settings_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_menu(callback, session)


@router.callback_query(F.data == "cardsettings:add", IsAdmin())
async def add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.update_data(cardsettings_mode="add")
    await state.set_state(MultiCardSettingsState.waiting_card_number)
    await callback.message.edit_text(
        "➕ <b>افزودن کارت جدید</b>\n\n"
        "شماره کارت ۱۶ رقمی را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data=NavAdminTools.CARD_SETTINGS)]]
        ),
    )


@router.callback_query(F.data.regexp(r"^cardsettings:edit:\d+$"), IsAdmin())
async def edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    card_id = int(callback.data.rsplit(":", 1)[1])
    await callback.answer()
    await state.clear()
    await state.update_data(cardsettings_mode="edit", cardsettings_card_id=card_id)
    await state.set_state(MultiCardSettingsState.waiting_card_number)
    await callback.message.edit_text(
        "✏️ <b>ویرایش کارت</b>\n\n"
        "شماره کارت ۱۶ رقمی جدید را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data=f"cardsettings:view:{card_id}")]]
        ),
    )


@router.message(MultiCardSettingsState.waiting_card_number, IsAdmin())
async def receive_card_number(message: Message, state: FSMContext) -> None:
    number = (message.text or "").strip().replace(" ", "").replace("-", "")
    if not number.isdigit() or len(number) != 16:
        await message.answer("❌ شماره کارت باید دقیقاً ۱۶ رقم باشد. دوباره وارد کنید.")
        return
    await state.update_data(cardsettings_card_number=number)
    await state.set_state(MultiCardSettingsState.waiting_bank_name)
    await message.answer(
        "🏦 <b>نام بانک</b> را وارد کنید:\n\n"
        "مثال: <code>بانک مسکن</code>"
    )


@router.message(MultiCardSettingsState.waiting_bank_name, IsAdmin())
async def receive_bank_name(message: Message, state: FSMContext) -> None:
    bank = " ".join((message.text or "").strip().split())
    if len(bank) < 2:
        await message.answer("❌ نام بانک معتبر نیست. دوباره وارد کنید.")
        return
    await state.update_data(cardsettings_bank_name=bank)
    await state.set_state(MultiCardSettingsState.waiting_holder_name)
    await message.answer(
        "👤 <b>نام و نام خانوادگی صاحب کارت</b> را وارد کنید:\n\n"
        "مثال: <code>امین احمدلو</code>"
    )


@router.message(MultiCardSettingsState.waiting_holder_name, IsAdmin())
async def receive_holder_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    holder = " ".join((message.text or "").strip().split())
    if len(holder) < 3:
        await message.answer("❌ نام و نام خانوادگی معتبر نیست. دوباره وارد کنید.")
        return

    data = await state.get_data()
    mode = data.get("cardsettings_mode")
    card_id = data.get("cardsettings_card_id")
    number = data["cardsettings_card_number"]
    bank = data["cardsettings_bank_name"]

    if mode == "edit" and isinstance(card_id, int):
        card = await _get_card(session, card_id)
        if not card:
            await state.clear()
            await message.answer("❌ کارت موردنظر پیدا نشد.")
            return
        card.card_number = number
        card.bank_name = bank
        card.card_holder_name = holder
        card.is_active = True
        await session.commit()
        await state.clear()
        await message.answer(
            "✅ <b>کارت با موفقیت ویرایش شد.</b>\n\n"
            f"💳 شماره کارت: <code>{number}</code>\n"
            f"🏦 بانک: <b>{bank}</b>\n"
            f"👤 بنام: <b>{holder}</b>",
            reply_markup=detail_markup(card),
        )
        return

    display_order = await CardSettings.next_display_order(session)
    card = CardSettings(
        card_number=number,
        bank_name=bank,
        card_holder_name=holder,
        display_order=display_order,
        is_active=True,
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    await state.clear()
    await message.answer(
        "✅ <b>کارت جدید با موفقیت اضافه شد.</b>\n\n"
        f"🔢 ترتیب: <b>{display_order}</b>\n"
        f"💳 شماره کارت: <code>{number}</code>\n"
        f"🏦 بانک: <b>{bank}</b>\n"
        f"👤 بنام: <b>{holder}</b>",
        reply_markup=detail_markup(card),
    )


@router.callback_query(F.data.regexp(r"^cardsettings:view:\d+$"), IsAdmin())
async def view_card(callback: CallbackQuery, session: AsyncSession) -> None:
    card_id = int(callback.data.rsplit(":", 1)[1])
    card = await _get_card(session, card_id)
    if not card:
        await callback.answer("❌ کارت پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    status = "🟢 فعال" if card.is_active else "🔴 غیرفعال"
    await callback.message.edit_text(
        "💳 <b>جزئیات کارت</b>\n\n"
        f"🔢 ترتیب: <b>{card.display_order}</b>\n"
        f"💳 شماره کارت: <code>{card.card_number}</code>\n"
        f"🏦 بانک: <b>{card.bank_name or 'ثبت نشده'}</b>\n"
        f"👤 بنام: <b>{card.card_holder_name}</b>\n"
        f"📌 وضعیت: <b>{status}</b>",
        reply_markup=detail_markup(card),
    )


@router.callback_query(F.data.regexp(r"^cardsettings:(enable|disable):\d+$"), IsAdmin())
async def toggle_card(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = (callback.data or "").split(":")
    action = parts[1]
    card_id = int(parts[2])
    card = await _get_card(session, card_id)
    if not card:
        await callback.answer("❌ کارت پیدا نشد.", show_alert=True)
        return
    if action == "enable" and (not card.card_number or not card.card_holder_name):
        await callback.answer("❌ ابتدا مشخصات کامل کارت را وارد کنید.", show_alert=True)
        return
    card.is_active = action == "enable"
    await session.commit()
    await callback.answer("🟢 کارت فعال شد." if card.is_active else "🔴 کارت غیرفعال شد.", show_alert=True)
    await view_card(callback, session)


@router.callback_query(F.data.regexp(r"^cardsettings:delete:\d+$"), IsAdmin())
async def delete_card(callback: CallbackQuery, session: AsyncSession) -> None:
    card_id = int(callback.data.rsplit(":", 1)[1])
    card = await _get_card(session, card_id)
    if not card:
        await callback.answer("❌ کارت پیدا نشد.", show_alert=True)
        return
    await session.delete(card)
    await session.commit()
    cards = await CardSettings.get_all(session)
    for index, item in enumerate(cards, start=1):
        item.display_order = index
    await session.commit()
    await callback.answer("🗑 کارت حذف شد.", show_alert=True)
    await _show_menu(callback, session)
