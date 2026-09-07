from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from app.bot.models import SubscriptionData
from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.db.models import ServicePurchasePlan, Transaction, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _restore_subscription(value, user_tg_id: int) -> SubscriptionData | None:
    try:
        if isinstance(value, str):
            data = SubscriptionData.deserialize(value)
        elif isinstance(value, dict):
            data = SubscriptionData(
                state=value.get("state", "config_name"),
                is_extend=bool(value.get("is_extend", False)),
                is_change=bool(value.get("is_change", False)),
                user_id=int(value.get("user_id", user_tg_id)),
                devices=int(value.get("devices", 0) or 0),
                duration=int(value.get("duration", 0) or 0),
                price=float(value.get("price", 0) or 0),
                original_price=float(value.get("original_price", 0) or 0),
                discount_percent=float(value.get("discount_percent", 0) or 0),
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
        .where(
            Transaction.tg_id == user.tg_id,
            Transaction.status == "pending",
        )
        .order_by(Transaction.created_at.desc())
    )
    for transaction in result.scalars().all():
        restored = _restore_subscription(transaction.subscription, user.tg_id)
        if restored is not None and restored.plan_id == plan_id:
            return restored
    return None


def _invoice_text(
    data: SubscriptionData,
    slug: str,
) -> str:
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
                    [InlineKeyboardButton(text="💳 پرداخت با درگاه واریزا", url=pay_url)],
                    [InlineKeyboardButton(text="🔙 بازگشت به فاکتور آبان گیت", callback_data="variza:back")],
                ]
            ),
        )
    except Exception as exc:
        logger.exception("Variza payment creation failed for user %s: %s", user.tg_id, exc)
        await callback.answer("❌ خطا در ایجاد پرداخت واریزا.", show_alert=True)


@router.callback_query(F.data == "variza:back")
async def variza_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>پرداخت کارت به کارت هوشمند</b>\n\n"
        "از دکمه پرداخت موردنظر خود استفاده کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 بازگشت به فاکتور", callback_data="main:menu")],
            ]
        ),
    )
