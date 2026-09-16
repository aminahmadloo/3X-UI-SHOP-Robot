from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.routers.my_services import handler as my_services_handler
from app.bot.utils.navigation import NavMain, NavSubscription, NavSupport
from app.db.models import Subscription, User

router = Router(name="my_services_auto_connect_details")


@router.callback_query(F.data.regexp(r"^my_services:view:\d+$"))
async def callback_my_service_details_with_auto_connect(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    await my_services_handler.callback_my_service_details(
        callback=callback,
        user=user,
        session=session,
        services=services,
    )

    if callback.message is None:
        return

    subscription_id = int(callback.data.rsplit(":", 1)[1])
    result = await session.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        return

    from app.bot.routers.my_services.handler import _status

    _, status_text = _status(subscription)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📱 اتصال خودکار",
            callback_data=f"my_services:auto:{subscription.id}",
        )
    )
    if subscription.status == "active" and status_text not in {"منقضی شده", "غیرفعال"}:
        builder.row(
            InlineKeyboardButton(
                text="🔗 دریافت لینک اتصال",
                callback_data=f"my_services:key:{subscription.id}",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🔄 تمدید سرویس",
                callback_data=f"main_renewal:service:{subscription.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="🛒 خرید سرویس جدید",
            callback_data=NavSubscription.BUY,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📚 راهنمای اتصال",
            callback_data=NavSupport.TRAINING,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⬅️ بازگشت به سرویس‌های من",
            callback_data=NavMain.MY_SERVICES,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به منوی اصلی",
            callback_data=NavMain.MAIN_MENU,
            style="danger",
        )
    )
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
