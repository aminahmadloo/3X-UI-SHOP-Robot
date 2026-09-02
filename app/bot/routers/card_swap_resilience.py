"""Resilient fallback for card-to-card swap after transient FSM loss.

The normal multi-card swap flow remains authoritative. This router only handles
its callback first so a wallet card-payment screen can still rotate cards when
its FSM payload is missing (for example after an in-memory FSM reset/restart).
"""

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.routers.multi_card_payment import swap_card as _normal_swap_card
from app.bot.routers.wallet.handler import CardPaymentState, card_text
from app.db.models import CardSettings, User

router = Router(name=__name__)

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _amount_from_payment_message(text: str | None) -> int:
    """Recover the displayed wallet amount when the FSM payload is unavailable."""
    if not text:
        return 0
    normalized = text.translate(_PERSIAN_DIGITS)
    match = re.search(
        r"مبلغ قابل پرداخت\s*:\s*(?:<[^>]+>)?\s*([\d,٬ ]+)\s*تومان",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"(?:amount|مبلغ)\s*:?\s*(?:<[^>]+>)?\s*([\d,٬ ]+)\s*(?:toman|تومان)",
            normalized,
            flags=re.IGNORECASE,
        )
    if not match:
        return 0
    raw = match.group(1).replace(",", "").replace("٬", "").replace(" ", "")
    try:
        return int(raw)
    except ValueError:
        return 0


async def _fallback_wallet_swap(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    current_id: int,
    amount: int,
) -> None:
    cards = await CardSettings.get_active_cards(session)
    if len(cards) <= 1:
        await callback.answer(
            "❌ کارت دیگری برای تعویض وجود ندارد.",
            show_alert=True,
        )
        return

    next_card = None
    for index, card in enumerate(cards):
        if card.id == current_id:
            next_card = cards[(index + 1) % len(cards)]
            break
    next_card = next_card or cards[0]

    await state.set_state(CardPaymentState.waiting_receipt)
    await state.update_data(
        card_payment_amount=amount,
        card_payment_card_id=next_card.id,
    )

    await callback.answer(
        "🔄 کارت عوض شد.\n\n"
        f"💳 شماره کارت جدید: {next_card.card_number}\n"
        f"🏦 بانک: {next_card.bank_name or 'نامشخص'}\n"
        f"👤 بنام: {next_card.card_holder_name}",
        show_alert=True,
    )
    await callback.message.edit_text(
        card_text(user.language_code, next_card, amount),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text={"text": next_card.card_number})],
                [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text={"text": str(amount)})],
                [InlineKeyboardButton(text="🔄 تعویض کارت", callback_data=f"multicard:swap:{next_card.id}")],
                [InlineKeyboardButton(text="✅ پرداخت کردم", callback_data="wallet:custom:paid")],
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="wallet")],
            ]
        ),
    )


@router.callback_query(F.data.regexp(r"^multicard:swap:\d+$"))
async def resilient_swap_card(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    stored_context = (
        data.get("custom_service_subscription")
        or data.get("subscription_data")
    )

    # If the normal purchase context is intact, use the existing implementation
    # unchanged. This keeps service/renewal behavior exactly as before.
    if stored_context or int(data.get("card_payment_amount", 0) or 0) > 0:
        await _normal_swap_card(callback, user, session, state)
        return

    # Wallet card-payment screens can survive visually after an FSM reset, but
    # the amount may no longer be in Redis. Recover it from the displayed text.
    amount = _amount_from_payment_message(callback.message.text if callback.message else None)
    if amount <= 0:
        await callback.answer(
            "❌ اطلاعات پرداخت منقضی شده است. لطفاً پرداخت کارت به کارت را دوباره شروع کنید.",
            show_alert=True,
        )
        return

    current_id = int((callback.data or "").rsplit(":", 1)[1])
    await _fallback_wallet_swap(callback, user, session, state, current_id, amount)
