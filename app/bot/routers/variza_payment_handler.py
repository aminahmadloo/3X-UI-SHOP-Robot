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
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription
from app.db.models import ServicePurchasePlan, Transaction, User

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


async def _resolve_subscription(user: User, plan_id: int, state: FSMContext, session: AsyncSession) -> SubscriptionData | None:
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


def _packed_subscription_data(packed: dict, user_tg_id: int, plan_id: int) -> SubscriptionData | None:
    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=packed.get("is_extend", False),
        is_change=packed.get("is_change", False),
        user_id=packed.get("user_id", user_tg_id),
        devices=packed.get("devices", 0),
        duration=int(packed.get("duration", 0) or 0),
        price=packed.get("price", 0),
        plan_id=packed.get("plan_id", plan_id),
        volume_gb=packed.get("volume_gb", 0),
        config_name=packed.get("config_name", ""),
    )
    data.subscription_id = packed.get("subscription_id", 0)
    if data.user_id != user_tg_id or data.plan_id != plan_id or data.price <= 0:
        return None
    return data


def _warning_text(provider: str) -> str:
    return (
        f"⚠️ <b>مهم:</b> مبلغ قابل پرداخت را <b>دقیقاً همان‌طور که در صفحه {provider} نمایش داده می‌شود</b> وارد کنید.\n"
        "در صورت واریز مبلغ متفاوت، تطبیق و تأیید خودکار پرداخت ممکن است انجام نشود."
    )


def gateway_choice_text(data: SubscriptionData) -> str:
    action = "تمدید سرویس" if data.is_extend else "خرید سرویس"
    return (
        "💳 <b>انتخاب درگاه پرداخت کارت به کارت هوشمند</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"نوع سفارش: <b>{action}</b>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"حجم: <code>{data.volume_gb} گیگ</code>\n"
        f"مدت: <code>{data.duration} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        "━━━━━━━━━━━━━━━\n\n"
        "لطفاً یکی از درگاه‌های کارت به کارت را انتخاب کنید."
    )


def gateway_choice_markup(plan_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="💳 پرداخت با درگاه آبان گیت", callback_data=f"cardgateway:aban:{plan_id}")]]
    if VarizaGateway.is_available():
        rows.append([InlineKeyboardButton(text="💳 پرداخت با درگاه واریزا", callback_data=f"variza:pay:{plan_id}")])
    rows.append([InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=f"mp_back:{plan_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _aban_invoice_text(data: SubscriptionData, invoice_id: str, order_id: str, payable_toman: float | int) -> str:
    volume_label = "حجم افزوده" if data.is_extend else "حجم"
    duration_label = "زمان افزوده" if data.is_extend else "مدت"
    return (
        "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"کد پیگیری: <code>{order_id}</code>\n"
        f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"{volume_label}: <code>{data.volume_gb} گیگ</code>\n"
        f"{duration_label}: <code>{data.duration} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"{_warning_text('آبان گیت')}\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        "پس از تأیید آبان گیت، شارژ یا سفارش شما به‌صورت خودکار انجام می‌شود."
    )


def _variza_invoice_text(
    data: SubscriptionData,
    slug: str,
) -> str:
    tracking_code = VarizaGateway.tracking_code_for_order(data)
    amount_line = (
        "مبلغ قابل واریز: "
        "<b>دقیقاً مطابق مبلغ نمایش‌داده‌شده در صفحه واریزا</b>"
    )
    volume_label = "حجم افزوده" if data.is_extend else "حجم"
    duration_label = "زمان افزوده" if data.is_extend else "مدت"
    success_text = "تمدید سرویس" if data.is_extend else "شارژ یا سفارش"
    return (
        "💳 <b>فاکتور کارت به کارت هوشمند واریزا</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"کد پیگیری: <code>{tracking_code}</code>\n"
        f"شماره فاکتور واریزا: <code>{slug}</code>\n"
        f"نام کانفیگ: <code>{data.config_name}</code>\n"
        f"{volume_label}: <code>{data.volume_gb} گیگ</code>\n"
        f"{duration_label}: <code>{data.duration} روز</code>\n"
        f"مبلغ سفارش: <code>{data.price:,.0f}</code> تومان\n"
        f"{amount_line}\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه واریزا</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"{_warning_text('واریزا')}\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        f"پس از تأیید واریزا، {success_text} شما به‌صورت خودکار انجام می‌شود."
    )


async def _show_aban_invoice(callback: CallbackQuery, data: SubscriptionData, aban_gateway: AbanGateway, invoice_id: str) -> None:
    invoice = await aban_gateway._get_invoice(invoice_id)
    order_id = str(invoice.get("order_id") or "").strip()
    payable_toman = invoice.get("payable_toman")
    if not order_id or payable_toman is None:
        raise RuntimeError("AbanGateway returned incomplete invoice details")
    pay_url = aban_gateway._payment_url(invoice_id, invoice)
    await callback.answer()
    await callback.message.edit_text(
        _aban_invoice_text(data, invoice_id, order_id, payable_toman),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
            [InlineKeyboardButton(text="🔙 انتخاب درگاه دیگر", callback_data=f"cardgateway:choice:{data.plan_id}")],
        ]),
    )


@router.callback_query(F.data.regexp(r"^mp:pay_aban:\d+$"))
async def legacy_aban_payment_selector(callback: CallbackQuery, user: User, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[-1])
    data = await _resolve_subscription(user, plan_id, state, session)
    if data is None:
        state_data = await state.get_data()
        packed = state_data.get("subscription_data")
        if isinstance(packed, str):
            try:
                restored = SubscriptionData.deserialize(packed)
                packed = {
                    "is_extend": restored.is_extend,
                    "is_change": restored.is_change,
                    "user_id": restored.user_id,
                    "devices": restored.devices,
                    "duration": restored.duration,
                    "price": restored.price,
                    "plan_id": restored.plan_id,
                    "volume_gb": restored.volume_gb,
                    "config_name": restored.config_name,
                    "subscription_id": restored.subscription_id,
                }
            except Exception:
                packed = None
        if isinstance(packed, dict):
            data = _packed_subscription_data(packed, user.tg_id, plan_id)
    if data is None:
        await callback.answer("❌ اطلاعات سفارش منقضی شده است.", show_alert=True)
        return
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not plan or plan.duration_days <= 0 or plan.volume_gb <= 0:
        await callback.answer("❌ پلن سفارش معتبر نیست.", show_alert=True)
        return
    await state.update_data(subscription_data=data.serialize())
    await callback.answer()
    await callback.message.edit_text(
        gateway_choice_text(data),
        reply_markup=gateway_choice_markup(plan_id),
    )


@router.callback_query(F.data.regexp(r"^cardgateway:aban:\d+$"))
async def choose_aban_gateway(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    gateway_factory,
) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[-1])
    data = await _resolve_subscription(user, plan_id, state, session)
    if data is None:
        await callback.answer("❌ اطلاعات سفارش منقضی شده است.", show_alert=True)
        return

    try:
        gateway = gateway_factory.get_gateway("pay_aban")
        if not isinstance(gateway, AbanGateway):
            raise RuntimeError("Configured pay_aban gateway is not an AbanGateway")

        pay_url = await gateway.create_payment(data)
        invoice_id = pay_url.rstrip("/").rsplit("/", 1)[-1]
        await _show_aban_invoice(callback, data, gateway, invoice_id)
    except Exception as exc:
        logger.exception("Aban payment creation failed for user %s: %s", user.tg_id, exc)
        await callback.answer("❌ خطا در ایجاد پرداخت آبان گیت.", show_alert=True)


@router.callback_query(F.data.regexp(r"^cardgateway:choice:\d+$"))
async def back_to_gateway_choice(callback: CallbackQuery, user: User, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[-1])
    data = await _resolve_subscription(user, plan_id, state, session)
    if data is None:
        await callback.answer("❌ اطلاعات سفارش منقضی شده است.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        gateway_choice_text(data),
        reply_markup=gateway_choice_markup(plan_id),
    )


@router.callback_query(F.data.regexp(r"^variza:pay:\d+$"))
async def create_variza_payment(callback: CallbackQuery, user: User, state: FSMContext, session: AsyncSession, variza_gateway: VarizaGateway) -> None:
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
            _variza_invoice_text(data, slug),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
                [InlineKeyboardButton(text="🔙 انتخاب درگاه دیگر", callback_data=f"cardgateway:choice:{plan_id}")],
            ]),
        )
    except Exception as exc:
        logger.exception("Variza payment creation failed for user %s: %s", user.tg_id, exc)
        await callback.answer("❌ خطا در ایجاد پرداخت واریزا.", show_alert=True)
