from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.routers.my_services.handler import (
    _days_left,
    _effective_expire_date,
    _status,
    _sync_subscriptions_with_xui,
)
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Promocode, Server, Subscription, User

router = Router(name=__name__)


class GiftCodeStates(StatesGroup):
    waiting_code = State()


def gift_prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت به کیف پول", callback_data=NavMain.WALLET)],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]
    )


def _gift_details_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 دریافت لینک اتصال", callback_data=f"my_services:key:{subscription_id}")],
            [InlineKeyboardButton(text="📦 سرویس‌های من", callback_data=NavMain.MY_SERVICES)],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]
    )


@router.callback_query(F.data == NavSubscription.GIFT_CODE)
async def gift_code_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GiftCodeStates.waiting_code)
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>کد هدیه</b>\n\n"
        "کد هدیه‌ات را ارسال کن تا کانفیگ هدیه برات ساخته بشه:",
        reply_markup=gift_prompt_keyboard(),
    )


@router.message(GiftCodeStates.waiting_code)
async def redeem_gift_code(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("❌ لطفاً کد هدیه را ارسال کن.", reply_markup=gift_prompt_keyboard())
        return

    promocode = await Promocode.get(session=session, code=code)
    if not promocode:
        await message.answer("❌ کد هدیه نامعتبر است.", reply_markup=gift_prompt_keyboard())
        return

    if not promocode.is_gift:
        await message.answer(
            "❌ این کد برای ساخت سرویس هدیه نیست.\n\nلطفاً کد هدیه معتبر را وارد کن.",
            reply_markup=gift_prompt_keyboard(),
        )
        return

    if promocode.is_activated:
        await message.answer("❌ این کد هدیه قبلاً استفاده شده است.", reply_markup=gift_prompt_keyboard())
        return

    volume_gb = int(promocode.volume_gb or 0)
    duration_days = int(promocode.duration or 0)
    if volume_gb <= 0 or duration_days <= 0:
        await message.answer("❌ مشخصات سرویس این کد هدیه نامعتبر است. لطفاً با پشتیبانی تماس بگیرید.")
        return

    await message.answer("⏳ در حال ساخت سرویس هدیه و کانفیگ شما...")

    config_name = await services.vpn._generate_unique_config_name(
        volume_gb=volume_gb,
        duration_days=duration_days,
        tg_id=user.tg_id,
    )

    client_id = await services.vpn.create_client(
        user=user,
        devices=1,
        duration=duration_days,
        total_gb=volume_gb,
        config_name=config_name,
    )
    if not client_id:
        await message.answer("❌ ساخت کانفیگ هدیه ناموفق بود. کد هدیه هنوز مصرف نشده است.")
        return

    async with services.vpn.session() as save_session:
        fresh_user = await User.get(session=save_session, tg_id=user.tg_id)
        if not fresh_user or fresh_user.server_id is None:
            await message.answer("❌ سرویس ساخته شد اما ثبت آن در حساب شما ناموفق بود. لطفاً با پشتیبانی تماس بگیرید.")
            return

        subscription = Subscription(
            user_id=fresh_user.id,
            server_id=fresh_user.server_id,
            plan_id=None,
            config_name=config_name,
            client_id=str(client_id),
            volume_gb=volume_gb,
            duration_days=duration_days,
            devices=1,
            is_gift=True,
            status="active",
            start_date=datetime.utcnow(),
            expire_date=datetime.utcnow() + timedelta(days=duration_days),
        )
        save_session.add(subscription)
        await save_session.flush()
        subscription_id = subscription.id

        # Consume the code only after the real XUI client and DB subscription
        # have both been created successfully.
        redeemed = await save_session.execute(
            select(Promocode)
            .where(Promocode.id == promocode.id, Promocode.is_activated.is_(False))
        )
        current_promocode = redeemed.scalar_one_or_none()
        if current_promocode is None:
            await save_session.rollback()
            await message.answer("❌ این کد هدیه هم‌زمان توسط درخواست دیگری مصرف شده است.")
            return

        current_promocode.is_activated = True
        current_promocode.activated_by = fresh_user.tg_id
        await save_session.commit()

    key = await services.vpn.get_key(user, subscription_id=subscription_id)
    links = await services.vpn.get_subscription_links(user, subscription_id=subscription_id)

    lines = [
        "🎁 <b>سرویس هدیه با موفقیت ساخته شد!</b>",
        "",
        f"💾 حجم: <b>{volume_gb} گیگ</b>",
        f"📅 مدت: <b>{duration_days} روز</b>",
        "👤 کاربر: <b>1</b>",
        f"📌 نام سرویس: <code>{config_name}</code>",
        "",
        "🔗 <b>کانفیگ هدیه</b>",
    ]

    if key:
        lines.extend(["", "🔗 لینک اشتراک:", f"<code>{key}</code>"])

    if links:
        lines.extend(["", "📡 لینک اتصال:"])
        for index, link in enumerate(links, start=1):
            lines.extend([f"🔹 اتصال {index}:", f"<code>{link}</code>"])

    lines.extend([
        "",
        "✅ این سرویس در «سرویس‌های من» ثبت شد.",
        "🚫 این سرویس هدیه قابلیت تمدید ندارد.",
    ])

    await state.clear()
    await message.answer(
        "\n".join(lines),
        reply_markup=_gift_details_keyboard(subscription_id),
    )


@router.callback_query(F.data.regexp(r"^my_services:view:\d+$"))
async def gift_service_details_guard(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    result = await session.execute(
        select(Subscription)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription or not subscription.is_gift:
        raise SkipHandler

    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    if not synced:
        await callback.answer("سرویس پیدا نشد.", show_alert=True)
        return
    subscription = synced[0]

    icon, status_text = _status(subscription)
    days = _days_left(subscription)
    expire = _effective_expire_date(subscription)
    server_name = subscription.server.name if subscription.server else "نامشخص"

    text = (
        "🎁 <b>سرویس هدیه</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{icon} <b>وضعیت:</b> {status_text}\n\n"
        f"📌 <b>نام سرویس:</b>\n<code>{subscription.config_name}</code>\n\n"
        f"💾 <b>حجم:</b> {subscription.volume_gb} GB\n"
        f"📅 <b>مدت:</b> {subscription.duration_days} روز\n"
        f"👤 <b>کاربر:</b> {subscription.devices}\n"
        f"🖥 <b>سرور:</b> {server_name}\n"
    )

    if subscription.start_date:
        text += f"🗓 <b>شروع:</b> {format_jalali(subscription.start_date)}\n"
    if expire:
        text += f"⏳ <b>انقضا:</b> {format_jalali(expire)}\n"
        if days is not None:
            text += f"📆 <b>باقی‌مانده:</b> {days} روز\n"

    text += "\n🚫 <b>این سرویس هدیه قابلیت تمدید ندارد.</b>"

    await callback.answer()
    await callback.message.edit_text(text=text, reply_markup=_gift_details_keyboard(subscription.id))
