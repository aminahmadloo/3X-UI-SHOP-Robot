from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways.aban_gateway import AbanGateway
from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.bot.utils.navigation import NavSubscription
from app.db.models import ServicePurchasePlan, Transaction, User
from app.bot.utils.constants import TransactionStatus

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _restore_subscription(value, user_tg_id: int) -> SubscriptionData | None:
    try:
        if isinstance(value, str):
            data = SubscriptionData.deserialize(value)
        elif isinstance(value, dict):
            data = SubscriptionData(
                state=NavSubscription.CONFIG_NAME,
                is_extend=bool(value.get("is_extend", False)),
                is_change=bool(value.get("is_change", False)),
                user_id=int(value.get("user_id", user_tg_id)),
                devices=int(value.get("devices", 0) or 0),
                duration=int(value.get("duration", 0) or 0),
                price=float(value.get("price", 0) or 0),
                original_price=int(value.get("original_price", 0) or 0),
                discount_percent=int(value.get("discount_percent", 0) or 0),
                discount_level_title=str(value.get("discount_level_title", "") or ""),
                plan_id=int(value.get("plan_id", 0) or 0),
                volume_gb=int(value.get("volume_gb", 0) or 0),
                config_name=str(value.get("config_name", "") or ""),
                payment_kind=str(value.get("payment_kind", "subscription") or "subscription"),
            )
            data.subscription_id = int(value.get("subscription_id", 0) or 0)
        else:
            return None
    except (TypeError, ValueError, AttributeError):
        return None

    if data.user_id != user_tg_id or data.price <= 0 or data.plan_id <= 0:
        return None
    return data


async def _resolve_subscription(
    user: User,
    plan_id: int,
    state: FSMContext,
    session: AsyncSession,
) -> SubscriptionData | None:
    state_data = await state.get_data()
    for key in ("subscription_data", "managed_card_subscription", "custom_service_subscription"):
        restored = _restore_subscription(state_data.get(key), user.tg_id)
        if restored is not None and restored.plan_id == plan_id:
            return restored

    result = await session.execute(
        select(Transaction)
        .where(Transaction.tg_id == user.tg_id, Transaction.status == TransactionStatus.PENDING)
        .order_by(Transaction.created_at.desc())
    )
    for transaction in result.scalars().all():
        restored = _restore_subscription(transaction.subscription, user.tg_id)
        if restored is not None and restored.plan_id == plan_id:
            return restored
    return None


def gateway_choice_text(data: SubscriptionData, payable_toman: float | int | None = None) -> str:
    payable = payable_toman if payable_toman is not None else data.price
    action = "تمدید سرویس" if data.is_extend else "خرید سرویس"
    return (
        "💳 <b>انتخاب درگاه پرداخت کارت به کارت هوشمند</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"نوع سفارش: <b>{action}</b>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"حجم: <code>{data.volume_gb} گیگ</code>\n"
        f"مدت: <code>{data.duration} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        f"مبلغ قابل پرداخت: <code>{float(payable):,.0f}</code> تومان\n"
        "━━━━━━━━━━━━━━━\n\n"
        "لطفاً یکی از درگاه‌های کارت به کارت را انتخاب کنید."
    )


def gateway_choice_markup(aban_invoice_id: str, plan_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 پرداخت با درگاه آبان گیت", callback_data=f"cardgateway:aban:{aban_invoice_id}")],
    ]
    if VarizaGateway.is_available():
        rows.append([InlineKeyboardButton(text="💳 پرداخت با درگاه واریزا", callback_data=f"variza:pay:{plan_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _aban_invoice_text(data: SubscriptionData, invoice_id: str, order_id: str, payable_toman: float | int) -> str:
    if data.is_extend:
        plan_volume = data.volume_gb
        plan_duration = data.duration
        volume_label = "حجم افزوده"
        duration_label = "زمان افزوده"
    else:
        plan_volume = data.volume_gb
        plan_duration = data.duration
        volume_label = "حجم"
        duration_label = "مدت"

    return (
        "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"کد پیگیری: <code>{order_id}</code>\n"
        f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"{volume_label}: <code>{plan_volume} گیگ</code>\n"
        f"{duration_label}: <code>{plan_duration} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        "پس از تأیید آبان گیت، شارژ یا سفارش شما به‌صورت خودکار انجام می‌شود."
    )


def _invoice_text(data: SubscriptionData, slug: str) -> str:
    tracking_code = VarizaGateway.tracking_code_for_slug(slug)
    if data.is_extend:
        return (
            "💳 <b>فاکتور کارت به کارت هوشمند واریزا</b>\n"
            "━━━━━━━━━━━━━━━\n"
            f"کد پیگیری: <code>{tracking_code}</code>\n"
            f"شماره فاکتور واریزا: <code>{slug}</code>\n"
            f"نام کانفیگ: <code>{data.config_name}</code>\n"
            f"حجم افزوده: <code>{data.volume_gb} گیگ</code>\n"
            f"زمان افزوده: <code>{data.duration} روز</code>\n"
            f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
            f"مبلغ قابل پرداخت: <code>{data.price:,.0f}</code> تومان\n"
            "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه واریزا</b>\n"
            "━━━━━━━━━━━━━━━\n\n"
            "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
            "پس از تأیید واریزا، تمدید سرویس به‌صورت خودکار انجام می‌شود."
        )
    return (
        "💳 <b>فاکتور کارت به کارت هوشمند واریزا</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"کد پیگیری: <code>{tracking_code}</code>\n"
        f"شماره فاکتور واریزا: <code>{slug}</code>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"حجم: <code>{data.volume_gb} گیگ</code>\n"
        f"مدت: <code>{data.duration} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        f"مبلغ قابل پرداخت: <code>{data.price:,.0f}</code> تومان\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه واریزا</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        "پس از تأیید واریزا، شارژ یا سفارش شما به‌صورت خودکار انجام می‌شود."
    )


@router.callback_query(F.data.regexp(r"^cardgateway:aban:[^:]+$"))
async def show_aban_invoice(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    aban_gateway: AbanGateway,
) -> None:
    invoice_id = (callback.data or "").rsplit(":", 1)[-1]
    try:
        async with session.bind.begin() if False else _noop_context():
            pass
    except Exception:
        pass

    async with session as db:
        transaction = await Transaction.get_by_id(session=db, payment_id=invoice_id)
        if transaction is None or transaction.tg_id != user.tg_id or transaction.status != TransactionStatus.PENDING:
            await callback.answer("❌ فاکتور آبان گیت معتبر نیست یا منقضی شده است.", show_alert=True)
            return
        data = _restore_subscription(transaction.subscription, user.tg_id)
        if data is None:
            await callback.answer("❌ اطلاعات سفارش معتبر نیست.", show_alert=True)
            return

    invoice = await aban_gateway._get_invoice(invoice_id)
    order_id = str(invoice.get("order_id") or "").strip()
    payable_toman = invoice.get("payable_toman")
    if not order_id or payable_toman is None:
        await callback.answer("❌ اطلاعات فاکتور آبان گیت ناقص است.", show_alert=True)
        return

    pay_url = aban_gateway._payment_url(invoice_id, invoice)
    await callback.answer()
    await callback.message.edit_text(
        _aban_invoice_text(data, invoice_id, order_id, payable_toman),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
            [InlineKeyboardButton(text="🔙 انتخاب درگاه دیگر", callback_data=f"cardgateway:choice:{data.plan_id}")],
        ]),
    )


@router.callback_query(F.data.regexp(r"^cardgateway:choice:\d+$"))
async def back_to_gateway_choice(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    aban_gateway: AbanGateway,
) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[-1])
    data = await _resolve_subscription(user, plan_id, state, session)
    if data is None:
        await callback.answer("❌ اطلاعات سفارش منقضی شده است.", show_alert=True)
        return
    async with session as db:
        result = await db.execute(
            select(Transaction)
            .where(
                Transaction.tg_id == user.tg_id,
                Transaction.status == TransactionStatus.PENDING,
                Transaction.subscription == data.serialize(),
            )
            .order_by(Transaction.created_at.desc())
        )
        transaction = result.scalars().first()
    payable = data.price
    invoice_id = transaction.payment_id if transaction else ""
    if invoice_id:
        try:
            invoice = await aban_gateway._get_invoice(invoice_id)
            payable = invoice.get("payable_toman", payable)
        except Exception:
            pass
    if not invoice_id:
        await callback.answer("❌ فاکتور آبان گیت پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        gateway_choice_text(data, payable),
        reply_markup=gateway_choice_markup(invoice_id, data.plan_id),
    )


@router.callback_query(F.data.regexp(r"^variza:pay:\d+$"))
async def create_variza_payment(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    variza_gateway: VarizaGateway,
) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[1])
    if not VarizaGateway.is_available():
        await callback.answer("❌ درگاه واریزا در حال حاضر فعال نیست.", show_alert=True)
        return

    data = await _resolve_subscription(user, plan_id, state, session)
    if data is None:
        await callback.answer("❌ اطلاعات سفارش منقضی شده است. لطفاً دوباره سفارش را ثبت کنید.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, plan_id)
    if not plan or plan.duration_days <= 0 or plan.volume_gb <= 0:
        await callback.answer("❌ پلن سفارش معتبر نیست.", show_alert=True)
        return

    try:
        pay_url = await variza_gateway.create_payment(data)
        slug = pay_url.rstrip("/").rsplit("/", 1)[-1]
        await callback.answer()
        await callback.message.edit_text(
            _invoice_text(data, slug),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
                    [InlineKeyboardButton(text="🔙 انتخاب درگاه دیگر", callback_data=f"cardgateway:choice:{plan_id}")],
                ]
            ),
        )
    except Exception as exc:
        logger.exception("Variza payment creation failed for user %s: %s", user.tg_id, exc)
        await callback.answer("❌ خطا در ایجاد پرداخت واریزا.", show_alert=True)


def _noop_context():
    class _Noop:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
    return _Noop()
