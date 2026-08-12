import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.filters import StateFilter

from app.bot.filters import IsAdmin
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY
from app.db.models import User
from app.db.models.wallet_topup_amount import WalletTopupAmount

logger = logging.getLogger(__name__)
router = Router(name=__name__)

WALLET_AMOUNT_MENU = "wallet_amounts"
WALLET_AMOUNT_ADD = "wallet_amounts:add"
WALLET_AMOUNT_EDIT = "wallet_amounts:edit"
WALLET_AMOUNT_DELETE = "wallet_amounts:delete"


class WalletAmountStates(StatesGroup):
    add_input = State()
    edit_input = State()


def _format_toman(amount: int) -> str:
    return f"{amount:,}".replace(",", "٬") + " تومان"


def wallet_amounts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ افزودن مبلغ", callback_data=WALLET_AMOUNT_ADD)],
            [InlineKeyboardButton(text="✏️ ویرایش مبلغ", callback_data=WALLET_AMOUNT_EDIT)],
            [InlineKeyboardButton(text="🗑 حذف مبلغ", callback_data=WALLET_AMOUNT_DELETE)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_tools")],
            [back_to_main_menu_button()],
        ]
    )


def amount_select_keyboard(amounts: list[WalletTopupAmount], action: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_format_toman(item.amount),
                callback_data=f"wallet_amounts:{action}:{item.id}",
            )
        ]
        for item in amounts
    ]
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=WALLET_AMOUNT_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_wallet_amounts(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.set_state(None)
    amounts = await WalletTopupAmount.get_all(session)
    if amounts:
        lines = "\n".join(
            f"{index}. {_format_toman(item.amount)}"
            for index, item in enumerate(amounts, start=1)
        )
    else:
        lines = "هنوز هیچ مبلغی ثبت نشده است."

    text = (
        "💰 <b>مدیریت مبالغ شارژ کیف پول</b>\n\n"
        "مبالغ آماده‌ای که کاربران در آینده برای شارژ کیف پول خواهند دید:\n\n"
        f"{lines}\n\n"
        "در این مرحله فقط مدیریت مبالغ آماده فعال است؛ بخش پرداخت و شارژ واقعی کیف پول بعداً اضافه می‌شود."
    )
    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    await message.bot.edit_message_text(
        text=text,
        chat_id=message.chat.id,
        message_id=main_message_id or message.message_id,
        reply_markup=wallet_amounts_keyboard(),
    )


@router.callback_query(F.data == WALLET_AMOUNT_MENU, IsAdmin())
async def callback_wallet_amounts(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    await callback.answer()
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await show_wallet_amounts(callback.message, state, session)


@router.callback_query(F.data == WALLET_AMOUNT_ADD, IsAdmin())
async def callback_wallet_amount_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WalletAmountStates.add_input)
    await callback.message.edit_text(
        "➕ <b>افزودن مبلغ شارژ</b>\n\n"
        "مبلغ را به تومان و به صورت عددی وارد کنید.\n"
        "مثال: <code>650000</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=WALLET_AMOUNT_MENU)]]
        ),
    )


@router.message(WalletAmountStates.add_input, IsAdmin())
async def handle_wallet_amount_add(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. فقط یک عدد مثبت به تومان وارد کنید.")
        return

    amount = int(raw)
    item = await WalletTopupAmount.create(session, amount)
    if not item:
        await message.answer("❌ این مبلغ قبلاً ثبت شده یا ذخیره آن ناموفق بود.")
        return

    await state.set_state(None)
    await show_wallet_amounts(message, state, session)


@router.callback_query(F.data == WALLET_AMOUNT_EDIT, IsAdmin())
async def callback_wallet_amount_edit(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    await callback.answer()
    amounts = await WalletTopupAmount.get_all(session)
    if not amounts:
        await callback.answer("هنوز مبلغی برای ویرایش وجود ندارد.", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ مبلغ مورد نظر برای ویرایش را انتخاب کنید:",
        reply_markup=amount_select_keyboard(amounts, "edit"),
    )


@router.callback_query(F.data.regexp(r"^wallet_amounts:edit:\d+$"), IsAdmin())
async def callback_wallet_amount_edit_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    amount_id = int(callback.data.rsplit(":", 1)[1])
    await state.set_state(WalletAmountStates.edit_input)
    await state.update_data(wallet_amount_id=amount_id, **{MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await callback.message.edit_text(
        "✏️ <b>ویرایش مبلغ</b>\n\n"
        "مبلغ جدید را به تومان وارد کنید.\n"
        "مثال: <code>750000</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=WALLET_AMOUNT_MENU)]]
        ),
    )


@router.message(WalletAmountStates.edit_input, IsAdmin())
async def handle_wallet_amount_edit(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. فقط یک عدد مثبت به تومان وارد کنید.")
        return

    data = await state.get_data()
    amount_id = data.get("wallet_amount_id")
    item = await WalletTopupAmount.update_amount(session, int(amount_id), int(raw))
    if not item:
        await message.answer("❌ ویرایش مبلغ انجام نشد.")
        return

    await state.set_state(None)
    await show_wallet_amounts(message, state, session)


@router.callback_query(F.data == WALLET_AMOUNT_DELETE, IsAdmin())
async def callback_wallet_amount_delete(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    await callback.answer()
    amounts = await WalletTopupAmount.get_all(session)
    if not amounts:
        await callback.answer("هنوز مبلغی برای حذف وجود ندارد.", show_alert=True)
        return
    await callback.message.edit_text(
        "🗑 مبلغ مورد نظر برای حذف را انتخاب کنید:",
        reply_markup=amount_select_keyboard(amounts, "delete"),
    )


@router.callback_query(F.data.regexp(r"^wallet_amounts:delete:\d+$"), IsAdmin())
async def callback_wallet_amount_delete_selected(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    await callback.answer()
    amount_id = int(callback.data.rsplit(":", 1)[1])
    deleted = await WalletTopupAmount.delete(session, amount_id)
    if not deleted:
        await callback.answer("❌ حذف مبلغ ناموفق بود.", show_alert=True)
        return

    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await show_wallet_amounts(callback.message, state, session)
