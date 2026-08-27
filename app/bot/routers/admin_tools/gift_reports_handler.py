from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Promocode, User

router = Router(name=__name__)


def _reports_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بروزرسانی", callback_data=NavAdminTools.GIFT_REPORTS)],
            [back_button(NavAdminTools.PROMOCODE_EDITOR)],
            [back_to_main_menu_button()],
        ]
    )


def _status(promocode: Promocode) -> str:
    if promocode.is_activated:
        return "✅ مصرف شده"
    if promocode.is_expired:
        return "⌛ منقضی شده"
    return "🟢 قابل استفاده"


def _date(value) -> str:
    return format_jalali(value) if value else "—"


@router.callback_query(F.data == NavAdminTools.GIFT_REPORTS, IsAdmin())
async def gift_reports(callback: CallbackQuery, session: AsyncSession) -> None:
    result = await session.execute(
        select(Promocode)
        .where(Promocode.is_gift.is_(True))
        .order_by(Promocode.id.desc())
        .limit(30)
    )
    promocodes = list(result.scalars().all())

    recipient_ids = {p.recipient_tg_id for p in promocodes if p.recipient_tg_id is not None}
    users_by_id: dict[int, User] = {}
    if recipient_ids:
        users_result = await session.execute(select(User).where(User.tg_id.in_(recipient_ids)))
        users_by_id = {user.tg_id: user for user in users_result.scalars().all()}

    activated_ids = {p.activated_by for p in promocodes if p.activated_by is not None}
    if activated_ids:
        users_result = await session.execute(select(User).where(User.tg_id.in_(activated_ids)))
        users_by_id.update({user.tg_id: user for user in users_result.scalars().all()})

    total = len(promocodes)
    sent = sum(1 for p in promocodes if p.recipient_tg_id is not None)
    activated = sum(1 for p in promocodes if p.is_activated)
    expired = sum(1 for p in promocodes if not p.is_activated and p.is_expired)
    available = total - activated - expired

    lines = [
        "📊 <b>گزارشات کدهای هدیه</b>",
        "",
        f"🎁 تعداد کدهای نمایش‌داده‌شده: <b>{total}</b>",
        f"📨 دارای گیرنده ثبت‌شده: <b>{sent}</b>",
        f"✅ مصرف‌شده: <b>{activated}</b>",
        f"⌛ منقضی‌شده و مصرف‌نشده: <b>{expired}</b>",
        f"🟢 قابل استفاده: <b>{available}</b>",
        "",
    ]

    if not promocodes:
        lines.append("هنوز کد هدیه‌ای ثبت نشده است.")
    else:
        lines.append("📋 <b>آخرین کدهای هدیه:</b>")
        for p in promocodes:
            recipient = users_by_id.get(p.recipient_tg_id) if p.recipient_tg_id else None
            recipient_text = (
                f"{recipient.first_name} | <code>{p.recipient_tg_id}</code>"
                if recipient
                else (f"<code>{p.recipient_tg_id}</code>" if p.recipient_tg_id else "ثبت نشده")
            )
            activated_text = f"<code>{p.activated_by}</code>" if p.activated_by else "—"
            lines.extend(
                [
                    "",
                    f"🔑 <code>{p.code}</code> | {_status(p)}",
                    f"👤 گیرنده: {recipient_text}",
                    f"📦 {p.volume_gb} GB | ⏱ {p.duration} روز",
                    f"🗓 ساخت: {_date(p.created_at)}",
                    f"⌛ انقضای کد: {_date(p.expires_at)}",
                    f"🎯 مصرف‌کننده: {activated_text}",
                ]
            )

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_reports_keyboard())
