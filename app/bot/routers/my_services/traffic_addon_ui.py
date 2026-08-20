from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.routers.my_services.client_control_handler import _render_details
from app.bot.routers.my_services.handler import _status, _sync_subscriptions_with_xui
from app.db.models import Server, Subscription, User

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

    if not callback.message or not callback.message.reply_markup:
        return

    _icon, status_text = _status(subscription)
    if subscription.status != "active" or status_text in {"منقضی شده", "غیرفعال"}:
        return

    rows = [list(row) for row in callback.message.reply_markup.inline_keyboard]
    if any(
        button.callback_data == f"traffic:add:{subscription.id}"
        for row in rows
        for button in row
    ):
        return

    insert_at = 2 if len(rows) >= 2 else len(rows)
    rows.insert(
        insert_at,
        [
            InlineKeyboardButton(
                text="📈 افزایش حجم",
                callback_data=f"traffic:add:{subscription.id}",
            )
        ],
    )
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
