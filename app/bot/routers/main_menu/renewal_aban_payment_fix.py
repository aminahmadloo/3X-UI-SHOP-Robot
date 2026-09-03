from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways.aban_gateway import AbanGateway
from app.bot.routers.main_menu.renew_service_handler import (
    PAYMENT_METHODS_PREFIX,
    _home_button,
    _resolve_renewal_payment_data,
)
from app.bot.routers.wallet.handler import has_pending_payment
from app.db.models import User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^main_renewal:gateway:\d+:\d+:pay_aban$"))
async def main_menu_aban_renewal_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    subscription_id = int(parts[2])
    plan_id = int(parts[3])

    if await has_pending_payment(session, user.tg_id):
        await callback.answer(
            "⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.",
            show_alert=True,
        )
        return

    resolved = await _resolve_renewal_payment_data(
        session, user, subscription_id, plan_id, services
    )
    if resolved is None:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        return

    subscription, plan, data = resolved
    await state.update_data(subscription_data=data.serialize())

    try:
        gateway = gateway_factory.get_gateway("pay_aban")
        if not isinstance(gateway, AbanGateway):
            raise RuntimeError("Configured pay_aban gateway is not an AbanGateway")

        pay_url = await gateway.create_payment(data)

        # create_payment persists the Aban invoice id in Transaction and returns
        # its payment URL. The invoice is fetched again so the user sees the
        # exact smart-invoice data returned by AbanGateway (order id and
        # payable amount), not the old generic renewal message.
        invoice_id = pay_url.rstrip("/").rsplit("/", 1)[-1]
        invoice = await gateway._get_invoice(invoice_id)
        order_id = str(invoice.get("order_id") or "").strip()
        payable_toman = invoice.get("payable_toman")

        if not invoice_id or not order_id or payable_toman is None:
            raise RuntimeError("AbanGateway returned incomplete invoice details")
    except Exception as exc:
        logger.exception(
            "Main-menu Aban renewal payment creation failed for user %s: %s",
            user.tg_id,
            exc,
        )
        await callback.answer(
            "❌ ایجاد فاکتور پرداخت تمدید انجام نشد. لطفاً دوباره تلاش کنید.",
            show_alert=True,
        )
        return

    text = (
        "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"کد پیگیری: <code>{order_id}</code>\n"
        f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"حجم افزوده: <code>{plan.volume_gb} گیگ</code>\n"
        f"زمان افزوده: <code>{plan.duration_days} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        "پس از تأیید آبان گیت، تمدید سرویس به‌صورت خودکار انجام می‌شود."
    )

    await callback.answer()
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
                [
                    InlineKeyboardButton(
                        text="🔙 تغییر روش پرداخت",
                        callback_data=f"{PAYMENT_METHODS_PREFIX}{subscription.id}:{plan.id}",
                    )
                ],
                [_home_button()],
            ]
        ),
    )
