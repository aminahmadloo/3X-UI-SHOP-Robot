from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways.aban_gateway import AbanGateway
from app.bot.routers.wallet.handler import has_pending_payment
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^wallet:method:gateway:\d+:pay_aban$"))
async def wallet_aban_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    amount = int(parts[3])

    if amount <= 0:
        await state.clear()
        await callback.answer("❌ مبلغ پرداخت معتبر نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer(
            "⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.",
            show_alert=True,
        )
        return

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=False,
        is_change=False,
        user_id=user.tg_id,
        devices=0,
        duration=0,
        price=amount,
        plan_id=0,
        volume_gb=0,
        config_name="wallet_topup",
        payment_kind="wallet_topup",
    )

    try:
        gateway = gateway_factory.get_gateway("pay_aban")
        if not isinstance(gateway, AbanGateway):
            raise RuntimeError("Configured pay_aban gateway is not an AbanGateway")

        pay_url = await gateway.create_payment(data)

        # create_payment stores the Aban invoice id in the pending Transaction.
        # Read it back instead of guessing it from payment_url, because Aban may
        # return a custom payment_url in the future.
        transaction = await gateway._find_pending_transaction(data)
        if transaction is None or not transaction.payment_id:
            raise RuntimeError("AbanGateway transaction was not persisted")

        invoice_id = str(transaction.payment_id).strip()
        invoice = await gateway._get_invoice(invoice_id)
        order_id = str(invoice.get("order_id") or "").strip()
        payable_toman = invoice.get("payable_toman")

        if not invoice_id or not order_id or payable_toman is None:
            raise RuntimeError("AbanGateway returned incomplete invoice details")
    except Exception as exc:
        logger.exception(
            "Wallet Aban payment creation failed for user %s: %s",
            user.tg_id,
            exc,
        )
        await callback.answer(
            "❌ ایجاد فاکتور شارژ کیف پول انجام نشد. لطفاً دوباره تلاش کنید.",
            show_alert=True,
        )
        return

    text = (
        "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"کد پیگیری: <code>{order_id}</code>\n"
        f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
        "نوع پرداخت: <code>شارژ کیف پول</code>\n"
        f"مبلغ شارژ: <code>{amount:,.0f}</code> تومان\n"
        f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        "پس از تأیید آبان گیت، مبلغ به‌صورت خودکار به کیف پول شما اضافه می‌شود."
    )

    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
                [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=NavMain.WALLET)],
            ]
        ),
    )
