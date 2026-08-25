from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.routers.my_services.client_control_handler import _render_details
from app.bot.routers.my_services.handler import _status, _sync_subscriptions_with_xui
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, Subscription, SubscriptionSettings, User

router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^my_services:view:\d+$"))
async def callback_my_service_details_with_traffic_button(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await callback.answer("سرویس پیدا نشد یا سرور آن دیگر فعال نیست.", show_alert=True)
        return

    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    if not synced:
        await callback.answer("این سرویس دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return

    subscription = synced[0]
    await callback.answer()
    await _render_details(callback, user, session, services, subscription)

    _icon, status_text = _status(subscription)
    if subscription.status != "active" or status_text in {"منقضی شده", "غیرفعال"}:
        return

    settings = await SubscriptionSettings.get_or_create(session)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔗 دریافت لینک اتصال",
            callback_data=f"my_services:key:{subscription.id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 تمدید سرویس",
            callback_data="main_menu:renew_service",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⏳ افزایش زمان سرویس",
            callback_data=NavSubscription.RENEW_SERVICE,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📈 افزایش حجم",
            callback_data=f"traffic:add:{subscription.id}",
        )
    )
    builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY))

    can_toggle = (
        settings.allow_user_client_toggle
        and status_text in {"فعال", "رو به اتمام"}
        and subscription.status in {"active", "inactive"}
    )
    if can_toggle:
        if subscription.status == "active":
            builder.row(
                InlineKeyboardButton(
                    text="⛔ غیرفعال کردن سرویس",
                    callback_data=f"my_services:toggle:{subscription.id}",
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text="✅ فعال کردن سرویس",
                    callback_data=f"my_services:toggle:{subscription.id}",
                )
            )

    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به سرویس‌های من", callback_data=NavMain.MY_SERVICES))
    builder.row(InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU))

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
